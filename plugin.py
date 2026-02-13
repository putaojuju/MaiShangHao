"""
麦上号 (MaiShangHao) - 离线消息同步插件

在机器人启动时，通过 NapCat API 拉取离线期间的群消息，
让麦麦能够"看到"下线期间收到的消息。

功能：
1. 调用 NapCat 的 get_group_msg_history API 获取群历史消息
2. 与数据库中已存储的消息进行对比，避免重复
3. 将新消息存入数据库，让麦麦能够"回忆"起这些消息
4. 同步完成后触发 planner 判断最新消息
5. 在离线消息前后添加标记，让 planner 和 replyer 识别

作者：putaojuju (葡萄)
仓库：https://github.com/putaojuju/MaiShangHao
"""

import aiohttp
import asyncio
import hashlib
import time
from typing import List, Tuple, Type, Any, Optional, Dict, Set
from src.plugin_system import (
    BasePlugin,
    register_plugin,
    BaseEventHandler,
    EventType,
    ConfigField,
    ComponentInfo,
)
from src.common.logger import get_logger
from src.common.database.database_model import Messages, ChatStreams
from src.config.config import global_config

logger = get_logger("MaiShangHao")

OFFLINE_MESSAGE_START = "【离线消息开始】以下是你下线期间收到的消息："
OFFLINE_MESSAGE_END = "【离线消息结束】以上是你下线期间收到的消息。"


class NapCatAPI:
    """NapCat API 调用封装"""

    def __init__(self, base_url: str, access_token: str = ""):
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def call_api(self, action: str, params: dict = None) -> dict:
        """调用 NapCat API"""
        session = await self._get_session()
        url = f"{self.base_url}/{action}"
        headers = {}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        try:
            async with session.post(url, json=params or {}, headers=headers, timeout=30) as resp:
                data = await resp.json()
                if data.get("status") == "ok":
                    return data.get("data", {})
                else:
                    logger.error(f"API 调用失败: {action} - {data}")
                    return {}
        except asyncio.TimeoutError:
            logger.error(f"API 调用超时: {action}")
            return {}
        except Exception as e:
            logger.error(f"API 调用异常: {action} - {e}")
            return {}

    async def get_group_msg_history(
        self, group_id: str, count: int = 50
    ) -> List[dict]:
        """获取群消息历史记录"""
        result = await self.call_api(
            "get_group_msg_history", {"group_id": int(group_id), "count": count}
        )
        return result.get("messages", [])

    async def get_group_list(self) -> List[dict]:
        """获取群列表"""
        return await self.call_api("get_group_list")

    async def get_group_member_info(self, group_id: str, user_id: str) -> dict:
        """获取群成员信息"""
        return await self.call_api(
            "get_group_member_info",
            {"group_id": int(group_id), "user_id": int(user_id)},
        )


class MaiShangHaoHandler(BaseEventHandler):
    """麦上号事件处理器 - 启动时同步离线消息"""

    event_type = EventType.ON_START
    handler_name = "mai_shang_hao_handler"
    handler_description = "启动时同步离线消息并触发 planner"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._synced = False

    async def execute(
        self, message=None
    ) -> Tuple[bool, bool, Optional[str], None, None]:
        if self._synced:
            return True, True, "已经同步过离线消息", None, None

        napcat_url = self.get_config("napcat.http_url", "http://127.0.0.1:3000")
        access_token = self.get_config("napcat.access_token", "")
        sync_groups = self.get_config("sync.groups", [])
        message_count = self.get_config("sync.message_count", 50)
        sync_delay = self.get_config("sync.delay_seconds", 5)
        bot_qq = self.get_config("sync.bot_qq", "")
        dedupe_mode = self.get_config("sync.dedupe_mode", "message_id")
        trigger_planner = self.get_config("sync.trigger_planner", True)
        planner_delay = self.get_config("sync.planner_delay", 3)
        add_markers = self.get_config("sync.add_markers", True)

        if not sync_groups:
            logger.info("[麦上号] 未配置需要同步的群，跳过同步")
            return True, True, "未配置同步群", None, None

        if not bot_qq:
            bot_qq = str(global_config.bot.qq_account)

        logger.info(f"[麦上号] 等待 {sync_delay} 秒后开始同步...")
        await asyncio.sleep(sync_delay)

        api = NapCatAPI(napcat_url, access_token)

        try:
            total_synced = 0
            total_skipped = 0
            synced_groups_info: List[Dict[str, Any]] = []

            for group_id in sync_groups:
                logger.info(f"[麦上号] 正在同步群 {group_id} 的消息...")
                
                synced, skipped, latest_msg = await self._sync_group_messages(
                    api=api,
                    group_id=str(group_id),
                    message_count=message_count,
                    bot_qq=bot_qq,
                    dedupe_mode=dedupe_mode,
                    add_markers=add_markers,
                )
                
                total_synced += synced
                total_skipped += skipped
                
                if latest_msg:
                    synced_groups_info.append({
                        "group_id": group_id,
                        "stream_id": self._generate_stream_id("qq", str(group_id)),
                        "latest_message": latest_msg,
                    })

                await asyncio.sleep(0.5)

            self._synced = True
            logger.info(
                f"[麦上号] 同步完成，新增 {total_synced} 条，跳过 {total_skipped} 条重复消息"
            )

            if trigger_planner and synced_groups_info:
                logger.info(f"[麦上号] 等待 {planner_delay} 秒后触发 planner...")
                await asyncio.sleep(planner_delay)
                
                await self._trigger_planner_for_groups(synced_groups_info)

            return (
                True,
                True,
                f"同步完成：新增 {total_synced} 条，跳过 {total_skipped} 条重复",
                None,
                None,
            )

        except Exception as e:
            logger.error(f"[麦上号] 同步失败: {e}", exc_info=True)
            return True, True, f"同步失败: {e}", None, None
        finally:
            await api.close()

    async def _sync_group_messages(
        self,
        api: NapCatAPI,
        group_id: str,
        message_count: int,
        bot_qq: str,
        dedupe_mode: str,
        add_markers: bool = True,
    ) -> Tuple[int, int, Optional[Dict]]:
        """同步单个群的消息
        
        Returns:
            (新增消息数, 跳过消息数, 最新消息信息)
        """
        messages = await api.get_group_msg_history(group_id, message_count)
        
        if not messages:
            logger.warning(f"[麦上号] 群 {group_id} 未获取到消息")
            return 0, 0, None

        logger.info(f"[麦上号] 群 {group_id} 获取到 {len(messages)} 条消息")

        stream_id = self._generate_stream_id("qq", group_id)
        
        existing_message_ids = await self._get_existing_message_ids(stream_id)
        existing_message_hashes = await self._get_existing_message_hashes(stream_id)

        synced = 0
        skipped = 0
        latest_msg_info: Optional[Dict] = None
        synced_messages: List[Dict] = []

        for msg in messages:
            try:
                msg_id = str(msg.get("message_id", ""))
                sender = msg.get("sender", {})
                sender_id = str(sender.get("user_id", ""))
                sender_name = sender.get("nickname", "未知")
                sender_card = sender.get("card", "") or sender_name
                msg_time = msg.get("time", 0)
                
                if str(sender_id) == str(bot_qq):
                    continue

                content = self._extract_text(msg)
                if not content or not content.strip():
                    continue

                should_skip = False
                if dedupe_mode == "message_id" and msg_id and msg_id in existing_message_ids:
                    should_skip = True
                elif dedupe_mode == "content_hash":
                    content_hash = self._generate_content_hash(sender_id, msg_time, content)
                    if content_hash in existing_message_hashes:
                        should_skip = True

                if should_skip:
                    skipped += 1
                    continue

                synced_messages.append({
                    "msg_id": msg_id,
                    "msg_time": msg_time,
                    "sender_id": sender_id,
                    "sender_name": sender_name,
                    "sender_card": sender_card,
                    "content": content,
                })
                
                latest_msg_info = {
                    "message_id": msg_id,
                    "time": msg_time,
                    "sender_id": sender_id,
                    "sender_name": sender_name,
                    "content": content,
                }

            except Exception as e:
                logger.error(f"[麦上号] 处理消息失败: {e}")
                skipped += 1

        if synced_messages:
            if add_markers and len(synced_messages) > 0:
                first_msg = synced_messages[0]
                last_msg = synced_messages[-1]
                
                success = await self._store_marker_message(
                    stream_id=stream_id,
                    group_id=group_id,
                    msg_time=first_msg["msg_time"] - 0.1,
                    marker_type="start",
                )
                if success:
                    synced += 1
                
            for msg_data in synced_messages:
                success = await self._store_message(
                    stream_id=stream_id,
                    group_id=group_id,
                    msg_id=msg_data["msg_id"],
                    msg_time=msg_data["msg_time"],
                    sender_id=msg_data["sender_id"],
                    sender_name=msg_data["sender_name"],
                    sender_card=msg_data["sender_card"],
                    content=msg_data["content"],
                )
                if success:
                    synced += 1
                else:
                    skipped += 1
            
            if add_markers and len(synced_messages) > 0:
                success = await self._store_marker_message(
                    stream_id=stream_id,
                    group_id=group_id,
                    msg_time=last_msg["msg_time"] + 0.1,
                    marker_type="end",
                )
                if success:
                    synced += 1

        logger.info(
            f"[麦上号] 群 {group_id} 同步完成：新增 {synced} 条，跳过 {skipped} 条"
        )
        return synced, skipped, latest_msg_info

    async def _store_marker_message(
        self,
        stream_id: str,
        group_id: str,
        msg_time: float,
        marker_type: str,
    ) -> bool:
        """存储离线消息标记"""
        try:
            bot_qq = str(global_config.bot.qq_account)
            bot_name = global_config.bot.nickname
            
            if marker_type == "start":
                marker_text = OFFLINE_MESSAGE_START
                msg_id = f"offline_marker_start_{int(msg_time * 1000)}"
            else:
                marker_text = OFFLINE_MESSAGE_END
                msg_id = f"offline_marker_end_{int(msg_time * 1000)}"
            
            current_time = time.time()

            def _db_operation():
                try:
                    chat_stream = ChatStreams.get_or_none(
                        ChatStreams.stream_id == stream_id
                    )
                    if not chat_stream:
                        chat_stream = ChatStreams.create(
                            stream_id=stream_id,
                            platform="qq",
                            group_platform="qq",
                            group_id=group_id,
                            group_name="",
                            user_platform="qq",
                            user_id=bot_qq,
                            user_nickname=bot_name,
                            user_cardname="",
                            create_time=msg_time,
                            last_active_time=current_time,
                        )
                    else:
                        chat_stream.last_active_time = current_time
                        chat_stream.save()
                except Exception as e:
                    logger.warning(f"[麦上号] 更新聊天流失败: {e}")

                existing = Messages.get_or_none(Messages.message_id == msg_id)
                if existing:
                    return False

                Messages.create(
                    message_id=msg_id,
                    time=float(msg_time),
                    chat_id=stream_id,
                    reply_to="",
                    interest_value=0,
                    key_words="",
                    key_words_lite="",
                    is_mentioned=False,
                    is_at=False,
                    reply_probability_boost=0.0,
                    chat_info_stream_id=stream_id,
                    chat_info_platform="qq",
                    chat_info_user_platform="qq",
                    chat_info_user_id=bot_qq,
                    chat_info_user_nickname=bot_name,
                    chat_info_user_cardname="",
                    chat_info_group_platform="qq",
                    chat_info_group_id=group_id,
                    chat_info_group_name="",
                    chat_info_create_time=msg_time,
                    chat_info_last_active_time=current_time,
                    user_platform="qq",
                    user_id=bot_qq,
                    user_nickname=bot_name,
                    user_cardname="",
                    processed_plain_text="",
                    display_message=marker_text,
                    priority_mode="",
                    priority_info="",
                    is_emoji=False,
                    is_picid=False,
                    is_command=False,
                    intercept_message_level=0,
                    is_notify=False,
                    selected_expressions="",
                )
                return True

            result = await asyncio.to_thread(_db_operation)
            if result:
                logger.debug(f"[麦上号] 存储标记消息: {marker_text}")
            return result

        except Exception as e:
            logger.error(f"[麦上号] 存储标记消息失败: {e}", exc_info=True)
            return False

    async def _trigger_planner_for_groups(self, groups_info: List[Dict[str, Any]]):
        """为同步的群触发 planner"""
        try:
            from src.chat.heart_flow.heartflow import heartflow
            from src.chat.heart_flow.heartFC_chat import HeartFChatting
            
            for group_info in groups_info:
                stream_id = group_info["stream_id"]
                group_id = group_info["group_id"]
                latest_msg = group_info.get("latest_message")
                
                if not latest_msg:
                    continue
                
                logger.info(f"[麦上号] 为群 {group_id} 触发 planner...")
                
                try:
                    chat_instance = await heartflow.get_or_create_heartflow_chat(stream_id)
                    
                    if chat_instance and isinstance(chat_instance, HeartFChatting):
                        chat_instance.last_read_time = latest_msg["time"] - 1
                        logger.info(
                            f"[麦上号] 已更新群 {group_id} 的读取时间戳，"
                            f"心流循环将自动处理新消息"
                        )
                    else:
                        logger.warning(
                            f"[麦上号] 群 {group_id} 的聊天实例创建失败或类型不正确"
                        )
                        
                except Exception as e:
                    logger.error(f"[麦上号] 触发群 {group_id} 的 planner 失败: {e}")
                    
                await asyncio.sleep(0.5)
                    
        except ImportError as e:
            logger.error(f"[麦上号] 导入心流模块失败: {e}")
        except Exception as e:
            logger.error(f"[麦上号] 触发 planner 失败: {e}", exc_info=True)

    async def _get_existing_message_ids(self, stream_id: str) -> Set[str]:
        """获取数据库中已存在的消息ID集合"""
        try:
            messages = await asyncio.to_thread(
                lambda: list(
                    Messages.select(Messages.message_id)
                    .where(Messages.chat_id == stream_id)
                    .execute()
                )
            )
            return {msg.message_id for msg in messages if msg.message_id}
        except Exception as e:
            logger.error(f"[麦上号] 获取已存在消息ID失败: {e}")
            return set()

    async def _get_existing_message_hashes(self, stream_id: str) -> Set[str]:
        """获取数据库中已存在的消息内容哈希集合"""
        try:
            messages = await asyncio.to_thread(
                lambda: list(
                    Messages.select(
                        Messages.user_id,
                        Messages.time,
                        Messages.processed_plain_text,
                    )
                    .where(Messages.chat_id == stream_id)
                    .execute()
                )
            )
            hashes = set()
            for msg in messages:
                if msg.user_id and msg.time and msg.processed_plain_text:
                    hash_val = self._generate_content_hash(
                        msg.user_id, msg.time, msg.processed_plain_text
                    )
                    hashes.add(hash_val)
            return hashes
        except Exception as e:
            logger.error(f"[麦上号] 获取已存在消息哈希失败: {e}")
            return set()

    def _generate_stream_id(self, platform: str, group_id: str) -> str:
        """生成聊天流ID（与 MaiBot 核心逻辑一致）"""
        components = [platform, str(group_id)]
        key = "_".join(components)
        return hashlib.md5(key.encode()).hexdigest()

    def _generate_content_hash(
        self, sender_id: str, msg_time: float, content: str
    ) -> str:
        """生成消息内容哈希，用于去重"""
        key = f"{sender_id}_{int(msg_time)}_{content[:100]}"
        return hashlib.md5(key.encode()).hexdigest()

    async def _store_message(
        self,
        stream_id: str,
        group_id: str,
        msg_id: str,
        msg_time: float,
        sender_id: str,
        sender_name: str,
        sender_card: str,
        content: str,
    ) -> bool:
        """存储消息到数据库"""
        try:
            current_time = time.time()

            def _db_operation():
                try:
                    chat_stream = ChatStreams.get_or_none(
                        ChatStreams.stream_id == stream_id
                    )
                    if not chat_stream:
                        chat_stream = ChatStreams.create(
                            stream_id=stream_id,
                            platform="qq",
                            group_platform="qq",
                            group_id=group_id,
                            group_name="",
                            user_platform="qq",
                            user_id=sender_id,
                            user_nickname=sender_name,
                            user_cardname=sender_card,
                            create_time=msg_time,
                            last_active_time=current_time,
                        )
                    else:
                        chat_stream.last_active_time = current_time
                        chat_stream.save()
                except Exception as e:
                    logger.warning(f"[麦上号] 更新聊天流失败: {e}")

                if msg_id:
                    existing = Messages.get_or_none(Messages.message_id == msg_id)
                    if existing:
                        return False

                Messages.create(
                    message_id=msg_id or f"sync_{int(msg_time * 1000)}_{sender_id}",
                    time=float(msg_time),
                    chat_id=stream_id,
                    reply_to="",
                    interest_value=0,
                    key_words="",
                    key_words_lite="",
                    is_mentioned=False,
                    is_at=False,
                    reply_probability_boost=0.0,
                    chat_info_stream_id=stream_id,
                    chat_info_platform="qq",
                    chat_info_user_platform="qq",
                    chat_info_user_id=sender_id,
                    chat_info_user_nickname=sender_name,
                    chat_info_user_cardname=sender_card,
                    chat_info_group_platform="qq",
                    chat_info_group_id=group_id,
                    chat_info_group_name="",
                    chat_info_create_time=msg_time,
                    chat_info_last_active_time=current_time,
                    user_platform="qq",
                    user_id=sender_id,
                    user_nickname=sender_name,
                    user_cardname=sender_card,
                    processed_plain_text=content,
                    display_message="",
                    priority_mode="",
                    priority_info="",
                    is_emoji=False,
                    is_picid=False,
                    is_command=False,
                    intercept_message_level=0,
                    is_notify=False,
                    selected_expressions="",
                )
                return True

            result = await asyncio.to_thread(_db_operation)
            return result

        except Exception as e:
            logger.error(f"[麦上号] 存储消息失败: {e}", exc_info=True)
            return False

    def _extract_text(self, msg: dict) -> str:
        """从消息中提取文本内容"""
        content = msg.get("content", [])
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = []
            for seg in content:
                if isinstance(seg, dict) and seg.get("type") == "text":
                    texts.append(seg.get("data", {}).get("text", ""))
            return "".join(texts)
        return ""


@register_plugin
class MaiShangHaoPlugin(BasePlugin):
    """麦上号 - 离线消息同步插件"""

    plugin_name: str = "mai_shang_hao"
    enable_plugin: bool = False
    dependencies: List[str] = []
    python_dependencies: List[str] = ["aiohttp"]
    config_file_name: str = "config.toml"

    config_section_descriptions = {
        "plugin": "插件基本信息",
        "napcat": "NapCat API 配置",
        "sync": "同步配置",
    }

    config_schema: dict = {
        "plugin": {
            "config_version": ConfigField(
                type=str, default="1.0.0", description="配置文件版本"
            ),
            "enabled": ConfigField(type=bool, default=False, description="是否启用插件"),
        },
        "napcat": {
            "http_url": ConfigField(
                type=str,
                default="http://127.0.0.1:3000",
                description="NapCat HTTP API 地址",
            ),
            "access_token": ConfigField(
                type=str, default="", description="NapCat access_token (如果有)"
            ),
        },
        "sync": {
            "groups": ConfigField(
                type=list,
                default=[],
                description="需要同步消息的群号列表，如 [123456789, 987654321]",
            ),
            "message_count": ConfigField(
                type=int, default=50, description="每个群同步的消息数量"
            ),
            "delay_seconds": ConfigField(
                type=int,
                default=5,
                description="启动后延迟多少秒开始同步（等待 NapCat 连接稳定）",
            ),
            "bot_qq": ConfigField(
                type=str,
                default="",
                description="机器人QQ号（用于过滤机器人自己发送的消息，留空则自动获取）",
            ),
            "dedupe_mode": ConfigField(
                type=str,
                default="message_id",
                description="去重模式：message_id（按消息ID去重）或 content_hash（按内容哈希去重）",
            ),
            "trigger_planner": ConfigField(
                type=bool,
                default=True,
                description="同步完成后是否触发 planner 判断最新消息",
            ),
            "planner_delay": ConfigField(
                type=int,
                default=3,
                description="同步完成后延迟多少秒触发 planner",
            ),
            "add_markers": ConfigField(
                type=bool,
                default=True,
                description="是否在离线消息前后添加标记，让 planner 和 replyer 识别",
            ),
        },
    }

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        return [
            (MaiShangHaoHandler.get_handler_info(), MaiShangHaoHandler)
        ]
