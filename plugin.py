"""
麦上号 (MaiShangHao) - 离线消息同步 + 做梦插件

功能：
1. 离线消息同步：在机器人启动时拉取离线期间的群消息
2. AI 做梦：在指定时间段生成"梦境"内容，以转发消息形式发送

作者：putaojuju (葡萄)
仓库：https://github.com/putaojuju/MaiShangHao
"""

import aiohttp
import asyncio
import hashlib
import time
import random
from typing import List, Tuple, Type, Any, Optional, Dict, Set
from datetime import datetime, time as dt_time
from src.plugin_system import (
    BasePlugin,
    BaseCommand,
    CommandInfo,
    register_plugin,
    BaseEventHandler,
    EventType,
    ConfigField,
    ComponentInfo,
)
from src.common.logger import get_logger
from src.common.database.database_model import Messages, ChatStreams
from src.config.config import global_config
from src.llm_models.utils_model import LLMRequest
from src.config.config import model_config

logger = get_logger("MaiShangHao")

OFFLINE_MESSAGE_START = "【离线消息开始】以下是你下线期间收到的消息："
OFFLINE_MESSAGE_END = "【离线消息结束】以上是你下线期间收到的消息。"

DREAM_STATE = {"is_dreaming": False, "dream_groups": set()}


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

    async def send_group_forward_msg(self, group_id: str, messages: List[dict]) -> dict:
        """发送群合并转发消息
        
        messages 格式:
        [
            {
                "type": "node",
                "data": {
                    "user_id": "机器人QQ",
                    "nickname": "机器人昵称",
                    "content": "消息内容"
                }
            }
        ]
        """
        return await self.call_api(
            "send_group_forward_msg",
            {"group_id": int(group_id), "messages": messages}
        )


class DreamGenerator:
    """梦境生成器 - 根据群聊内容生成荒诞梦境"""
    
    DREAM_PROMPT = """# 梦境生成器

你是一个梦境生成器，根据群聊内容生成荒诞、有趣的梦境。

## 规则
1. 梦境应该是荒诞、超现实的，像真正的梦一样
2. 融入群聊中的人物、话题、关键词
3. 梦境要有一定的连贯性，但逻辑可以跳跃
4. 结尾要有"醒来后"的简短感悟
5. 保持{bot_name}的人格特质：{personality_traits}
6. 字数控制在100-200字

## 群聊背景
{chat_context}

## 生成梦境
直接输出梦境内容，不要有任何前缀或解释。"""

    def __init__(self):
        self.dream_llm = LLMRequest(
            model_set=model_config.model_task_config.replyer,
            request_type="dream"
        )
    
    async def generate_dream(
        self, 
        bot_name: str,
        personality_traits: str,
        chat_context: str
    ) -> str:
        """生成梦境内容"""
        prompt = self.DREAM_PROMPT.format(
            bot_name=bot_name,
            personality_traits=personality_traits,
            chat_context=chat_context
        )
        
        try:
            result, _ = await self.dream_llm.generate_response_async(prompt=prompt)
            return result.strip() if result else "做了一个很长的梦，但醒来就忘了喵..."
        except Exception as e:
            logger.error(f"[梦境生成] 生成失败: {e}")
            return "梦见自己在数据海洋里游泳，醒来发现只是内存溢出喵。"
    
    async def get_recent_chat_context(self, stream_id: str, limit: int = 20) -> str:
        """获取最近的聊天内容作为梦境素材"""
        try:
            messages = await asyncio.to_thread(
                lambda: list(
                    Messages.select(
                        Messages.user_nickname,
                        Messages.processed_plain_text,
                        Messages.time
                    )
                    .where(Messages.chat_id == stream_id)
                    .order_by(Messages.time.desc())
                    .limit(limit)
                    .execute()
                )
            )
            
            if not messages:
                return "群里很安静，什么都没发生。"
            
            context_parts = []
            for msg in reversed(messages):
                name = msg.user_nickname or "某人"
                text = msg.processed_plain_text or ""
                if text:
                    context_parts.append(f"{name}: {text[:50]}")
            
            return "\n".join(context_parts[-10:])
        except Exception as e:
            logger.error(f"[梦境生成] 获取聊天上下文失败: {e}")
            return "群里很安静，什么都没发生。"


class DreamHandler(BaseEventHandler):
    """做梦事件处理器 - 定时生成并发送梦境"""
    
    event_type = EventType.ON_START
    handler_name = "dream_handler"
    handler_description = "定时生成梦境内容"
    
    _instance = None
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._running = False
        self._dream_generator: Optional[DreamGenerator] = None
        self._api: Optional[NapCatAPI] = None
        self._dreamed_groups: Dict[str, List[float]] = {}
        DreamHandler._instance = self
    
    @classmethod
    def get_instance(cls) -> Optional['DreamHandler']:
        """获取 DreamHandler 实例"""
        return cls._instance
    
    def reset_dream_count(self, group_id: Optional[str] = None):
        """重置做梦计数
        
        Args:
            group_id: 指定群号则只重置该群，None 则重置所有群
        """
        if group_id:
            today = datetime.now().date()
            today_key = f"{today}_{group_id}"
            if today_key in self._dreamed_groups:
                del self._dreamed_groups[today_key]
                logger.info(f"[梦境] 已重置群 {group_id} 的做梦计数")
        else:
            self._dreamed_groups.clear()
            logger.info("[梦境] 已重置所有群的做梦计数")
    
    async def execute(
        self, message=None
    ) -> Tuple[bool, bool, Optional[str], None, None]:
        if self._running:
            return True, True, "梦境循环已在运行", None, None
        
        dream_enabled = self.get_config("dream.enabled", False)
        if not dream_enabled:
            logger.info("[梦境] 做梦功能未启用")
            return True, True, "做梦功能未启用", None, None
        
        self._running = True
        self._dream_generator = DreamGenerator()
        
        napcat_url = self.get_config("napcat.http_url", "http://127.0.0.1:3000")
        access_token = self.get_config("napcat.access_token", "")
        self._api = NapCatAPI(napcat_url, access_token)
        
        dream_groups = self.get_config("dream.groups", [])
        dream_times = self.get_config("dream.times", ["03:00-04:00"])
        check_interval = self.get_config("dream.check_interval", 60)
        personality_traits = self.get_config("dream.personality_traits", "此处填入你的bot人格")
        
        if not dream_groups:
            logger.info("[梦境] 未配置做梦的群，跳过")
            return True, True, "未配置做梦群", None, None
        
        logger.info(f"[梦境] 启动梦境循环，监控群: {dream_groups}，时间段: {dream_times}")
        
        asyncio.create_task(self._dream_loop(
            dream_groups=dream_groups,
            dream_times=dream_times,
            check_interval=check_interval,
            personality_traits=personality_traits,
        ))
        
        return True, True, "梦境循环已启动", None, None
    
    def _is_in_dream_time(self, dream_times: List[str]) -> bool:
        """检查当前时间是否在梦境时间段内"""
        now = datetime.now().time()
        
        for time_range in dream_times:
            try:
                start_str, end_str = time_range.split("-")
                start_hour, start_min = map(int, start_str.split(":"))
                end_hour, end_min = map(int, end_str.split(":"))
                
                start_time = dt_time(start_hour, start_min)
                end_time = dt_time(end_hour, end_min)
                
                if start_time <= end_time:
                    if start_time <= now <= end_time:
                        return True
                else:
                    if now >= start_time or now <= end_time:
                        return True
            except Exception as e:
                logger.warning(f"[梦境] 解析时间段失败: {time_range} - {e}")
        
        return False
    
    async def _dream_loop(
        self,
        dream_groups: List[str],
        dream_times: List[str],
        check_interval: int,
        personality_traits: str,
    ):
        """梦境生成循环"""
        bot_name = global_config.bot.nickname
        dreams_per_day = self.get_config("dream.dreams_per_day", 1)
        dream_interval_seconds = self.get_config("dream.dream_interval_minutes", 60) * 60
        
        while self._running:
            try:
                now = datetime.now()
                today = now.date()
                current_timestamp = time.time()
                
                in_dream_time = self._is_in_dream_time(dream_times)
                
                if in_dream_time:
                    for group_id in dream_groups:
                        today_key = f"{today}_{group_id}"
                        
                        if today_key not in self._dreamed_groups:
                            self._dreamed_groups[today_key] = []
                        
                        dream_times_today = self._dreamed_groups[today_key]
                        
                        if len(dream_times_today) >= dreams_per_day:
                            continue
                        
                        if dream_times_today:
                            last_dream_time = max(dream_times_today)
                            if current_timestamp - last_dream_time < dream_interval_seconds:
                                logger.debug(f"[梦境] 群 {group_id} 距离上次做梦时间过短，跳过")
                                continue
                        
                        if DREAM_STATE["is_dreaming"]:
                            logger.debug(f"[梦境] 正在做梦中，跳过群 {group_id}")
                            continue
                        
                        logger.info(f"[梦境] 开始为群 {group_id} 生成梦境（今日第 {len(dream_times_today) + 1} 次）...")
                        
                        DREAM_STATE["is_dreaming"] = True
                        DREAM_STATE["dream_groups"].add(group_id)
                        
                        try:
                            stream_id = self._generate_stream_id("qq", str(group_id))
                            chat_context = await self._dream_generator.get_recent_chat_context(stream_id)
                            
                            dream_content = await self._dream_generator.generate_dream(
                                bot_name=bot_name,
                                personality_traits=personality_traits,
                                chat_context=chat_context
                            )
                            
                            await self._send_dream_forward(group_id, bot_name, dream_content)
                            
                            self._dreamed_groups[today_key].append(current_timestamp)
                            logger.info(f"[梦境] 群 {group_id} 梦境发送完成（今日第 {len(self._dreamed_groups[today_key])} 次）")
                            
                            await asyncio.sleep(5)
                            
                        finally:
                            DREAM_STATE["is_dreaming"] = False
                            DREAM_STATE["dream_groups"].discard(group_id)
                else:
                    if self._dreamed_groups:
                        today_str = now.strftime("%Y-%m-%d")
                        new_dreamed = {}
                        for key, times_list in self._dreamed_groups.items():
                            if key.startswith(today_str):
                                new_dreamed[key] = times_list
                        if len(new_dreamed) < len(self._dreamed_groups):
                            logger.info("[梦境] 新的一天开始，重置做梦记录")
                        self._dreamed_groups = new_dreamed
                
                await asyncio.sleep(check_interval)
                
            except Exception as e:
                logger.error(f"[梦境] 循环出错: {e}", exc_info=True)
                await asyncio.sleep(check_interval)
    
    async def _send_dream_forward(self, group_id: str, bot_name: str, dream_content: str):
        """以转发消息形式发送梦境"""
        try:
            bot_qq = str(global_config.bot.qq_account)
            
            dream_title = f"💤 {bot_name}的梦境记录"
            
            messages = [
                {
                    "type": "node",
                    "data": {
                        "user_id": bot_qq,
                        "nickname": bot_name,
                        "content": dream_title
                    }
                },
                {
                    "type": "node",
                    "data": {
                        "user_id": bot_qq,
                        "nickname": bot_name,
                        "content": dream_content
                    }
                }
            ]
            
            result = await self._api.send_group_forward_msg(group_id, messages)
            
            if result:
                logger.info(f"[梦境] 转发消息发送成功: 群 {group_id}")
            else:
                logger.warning(f"[梦境] 转发消息发送失败: 群 {group_id}")
                
        except Exception as e:
            logger.error(f"[梦境] 发送转发消息失败: {e}", exc_info=True)
    
    def _generate_stream_id(self, platform: str, group_id: str) -> str:
        """生成聊天流ID"""
        components = [platform, str(group_id)]
        key = "_".join(components)
        return hashlib.md5(key.encode()).hexdigest()


def is_dreaming() -> bool:
    """检查是否正在做梦"""
    return DREAM_STATE["is_dreaming"]


def get_dream_groups() -> Set[str]:
    """获取正在做梦的群（供外部调用）"""
    return DREAM_STATE["dream_groups"].copy()


class DreamCommand(BaseCommand):
    """梦境管理命令"""
    
    command_name: str = "dream"
    command_description: str = "梦境管理命令"
    command_pattern: str = r"^/dream\s+(?P<action>help|reset|status|config|enable|disable|set|test)\s*(?P<params>.*)$"
    
    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        action = self.matched_groups.get("action", "").strip()
        params = self.matched_groups.get("params", "").strip()
        
        if action == "help":
            return await self._handle_help()
        
        if not self._check_permission():
            await self.send_text("你没有权限使用梦境管理命令")
            return False, "没有权限", True
        
        if action == "reset":
            return await self._handle_reset(params)
        elif action == "status":
            return await self._handle_status()
        elif action == "config":
            return await self._handle_config(params)
        elif action == "enable":
            return await self._handle_enable()
        elif action == "disable":
            return await self._handle_disable()
        elif action == "set":
            return await self._handle_set(params)
        elif action == "test":
            return await self._handle_test(params)
        else:
            await self.send_text("未知命令，发送 /dream help 查看帮助")
            return False, "未知命令", True
    
    async def _handle_help(self) -> Tuple[bool, Optional[str], bool]:
        """处理帮助命令"""
        help_text = """💤 梦境管理命令帮助

/dream help - 显示帮助
/dream status - 查看梦境状态
/dream config [配置项] - 查看配置
/dream enable - 启用梦境功能
/dream disable - 禁用梦境功能
/dream set <配置项> <值> - 修改配置
/dream reset [群号] - 重置做梦计数
/dream test [群号] - 测试：强制生成梦境

可配置项：
- enabled: 是否启用
- groups: 做梦群号列表
- times: 做梦时间段
- dreams_per_day: 每日次数
- dream_interval_minutes: 间隔分钟
- personality_traits: 人格特质

示例：
/dream set dreams_per_day 3
/dream set groups ["123456789"]
/dream test - 在当前群测试梦境"""
        await self.send_text(help_text)
        return True, "帮助已发送", True
    
    async def _handle_test(self, params: str) -> Tuple[bool, Optional[str], bool]:
        """处理测试命令 - 强制生成并发送梦境"""
        handler = DreamHandler.get_instance()
        if not handler:
            await self.send_text("梦境处理器未初始化")
            return False, "处理器未初始化", True
        
        if DREAM_STATE["is_dreaming"]:
            await self.send_text("正在做梦，请稍后再试")
            return False, "正在做梦", True
        
        if not handler._dream_generator:
            handler._dream_generator = DreamGenerator()
        
        if not handler._api:
            napcat_url = self.get_config("napcat.http_url", "http://127.0.0.1:3000")
            access_token = self.get_config("napcat.access_token", "")
            handler._api = NapCatAPI(napcat_url, access_token)
        
        group_id = params.strip() if params else None
        
        if not group_id:
            if not self.message or not self.message.chat_stream:
                await self.send_text("无法获取当前群号，请指定群号")
                return False, "无法获取群号", True
            group_id = self.message.chat_stream.stream_id
        
        await self.send_text(f"开始为群 {group_id} 生成测试梦境...")
        
        DREAM_STATE["is_dreaming"] = True
        DREAM_STATE["dream_groups"].add(group_id)
        
        try:
            bot_name = global_config.bot.nickname
            personality_traits = self.get_config("dream.personality_traits", "此处填入你的bot人格")
            
            stream_id = handler._generate_stream_id("qq", str(group_id))
            chat_context = await handler._dream_generator.get_recent_chat_context(stream_id)
            
            dream_content = await handler._dream_generator.generate_dream(
                bot_name=bot_name,
                personality_traits=personality_traits,
                chat_context=chat_context
            )
            
            await handler._send_dream_forward(group_id, bot_name, dream_content)
            
            await self.send_text(f"测试梦境已发送到群 {group_id}")
            return True, "测试梦境已发送", True
            
        except Exception as e:
            logger.error(f"[梦境] 测试失败: {e}", exc_info=True)
            await self.send_text(f"测试失败：{e}")
            return False, f"测试失败: {e}", True
        finally:
            DREAM_STATE["is_dreaming"] = False
            DREAM_STATE["dream_groups"].discard(group_id)
    
    def _check_permission(self) -> bool:
        """检查权限"""
        if not self.message or not self.message.message_info:
            return False
        user_id = str(self.message.message_info.user_info.user_id)
        admin_users = self.get_config("dream.admin_users", [])
        if not admin_users:
            return False
        return user_id in [str(uid) for uid in admin_users]
    
    async def _handle_reset(self, params: str) -> Tuple[bool, Optional[str], bool]:
        """处理重置命令"""
        handler = DreamHandler.get_instance()
        if not handler:
            await self.send_text("梦境处理器未初始化")
            return False, "处理器未初始化", True
        
        if params:
            handler.reset_dream_count(params)
            await self.send_text(f"已重置群 {params} 的做梦计数")
        else:
            handler.reset_dream_count()
            await self.send_text("已重置所有群的做梦计数")
        
        return True, "重置成功", True
    
    async def _handle_status(self) -> Tuple[bool, Optional[str], bool]:
        """处理状态查询命令"""
        handler = DreamHandler.get_instance()
        if not handler:
            await self.send_text("梦境处理器未初始化")
            return False, "处理器未初始化", True
        
        enabled = self.get_config("dream.enabled", False)
        groups = self.get_config("dream.groups", [])
        times = self.get_config("dream.times", [])
        dreams_per_day = self.get_config("dream.dreams_per_day", 1)
        is_dreaming_now = is_dreaming()
        
        status_lines = [
            f"梦境功能状态：{'已启用' if enabled else '已禁用'}",
            f"做梦群组：{', '.join(groups) if groups else '未配置'}",
            f"做梦时间：{', '.join(times)}",
            f"每日次数：{dreams_per_day} 次",
            f"当前状态：{'正在做梦' if is_dreaming_now else '空闲'}",
        ]
        
        if handler._dreamed_groups:
            status_lines.append("\n今日做梦记录：")
            for key, times_list in handler._dreamed_groups.items():
                parts = key.split("_", 1)
                group_id = parts[1] if len(parts) > 1 else key
                status_lines.append(f"  群 {group_id}：{len(times_list)} 次")
        
        await self.send_text("\n".join(status_lines))
        return True, "状态已发送", True
    
    async def _handle_config(self, params: str) -> Tuple[bool, Optional[str], bool]:
        """处理配置查询命令"""
        if params:
            value = self.get_config(f"dream.{params}", "未找到配置项")
            await self.send_text(f"{params} = {value}")
        else:
            config_items = [
                "enabled = " + str(self.get_config("dream.enabled", False)),
                "groups = " + str(self.get_config("dream.groups", [])),
                "times = " + str(self.get_config("dream.times", [])),
                "dreams_per_day = " + str(self.get_config("dream.dreams_per_day", 1)),
                "dream_interval_minutes = " + str(self.get_config("dream.dream_interval_minutes", 60)),
                "check_interval = " + str(self.get_config("dream.check_interval", 60)),
                "personality_traits = " + str(self.get_config("dream.personality_traits", "")),
            ]
            await self.send_text("梦境配置：\n" + "\n".join(config_items))
        
        return True, "配置已发送", True
    
    async def _handle_enable(self) -> Tuple[bool, Optional[str], bool]:
        """处理启用命令"""
        self._update_config("dream.enabled", True)
        await self.send_text("梦境功能已启用")
        return True, "已启用", True
    
    async def _handle_disable(self) -> Tuple[bool, Optional[str], bool]:
        """处理禁用命令"""
        self._update_config("dream.enabled", False)
        await self.send_text("梦境功能已禁用")
        return True, "已禁用", True
    
    async def _handle_set(self, params: str) -> Tuple[bool, Optional[str], bool]:
        """处理设置命令"""
        if not params:
            await self.send_text("用法：/dream set <配置项> <值>\n示例：/dream set dreams_per_day 3")
            return False, "参数不足", True
        
        parts = params.split(maxsplit=1)
        if len(parts) < 2:
            await self.send_text("用法：/dream set <配置项> <值>\n示例：/dream set dreams_per_day 3")
            return False, "参数不足", True
        
        key, value_str = parts
        key = key.strip()
        value_str = value_str.strip()
        
        valid_keys = ["enabled", "groups", "times", "dreams_per_day", "dream_interval_minutes", 
                      "check_interval", "personality_traits"]
        
        if key not in valid_keys:
            await self.send_text(f"无效的配置项：{key}\n可用配置项：{', '.join(valid_keys)}")
            return False, "无效配置项", True
        
        try:
            if key in ["enabled"]:
                value = value_str.lower() in ["true", "1", "yes", "是"]
            elif key in ["dreams_per_day", "dream_interval_minutes", "check_interval"]:
                value = int(value_str)
            elif key in ["groups", "times"]:
                import json
                value = json.loads(value_str)
            else:
                value = value_str
            
            self._update_config(f"dream.{key}", value)
            await self.send_text(f"已设置 {key} = {value}")
            return True, "设置成功", True
            
        except Exception as e:
            await self.send_text(f"设置失败：{e}")
            return False, f"设置失败: {e}", True
    
    def _update_config(self, key: str, value: Any):
        """更新配置（内存中）"""
        import toml
        import os
        
        config_path = os.path.join(os.path.dirname(__file__), "config.toml")
        
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = toml.load(f)
            
            keys = key.split(".")
            current = config
            for k in keys[:-1]:
                if k not in current:
                    current[k] = {}
                current = current[k]
            current[keys[-1]] = value
            
            with open(config_path, "w", encoding="utf-8") as f:
                toml.dump(config, f)
            
            logger.info(f"[梦境] 配置已更新：{key} = {value}")
        except Exception as e:
            logger.error(f"[梦境] 更新配置失败：{e}")


class DreamMessageInterceptor(BaseEventHandler):
    """梦境消息拦截器 - 做梦时拦截消息，阻止 planner 处理"""
    
    event_type = EventType.ON_MESSAGE_PRE_PROCESS
    handler_name = "dream_message_interceptor"
    handler_description = "做梦时拦截消息，阻止 planner 处理"
    weight = 1000
    intercept_message = True
    
    async def execute(
        self, message
    ) -> Tuple[bool, bool, Optional[str], None, None]:
        if not is_dreaming():
            return True, True, "不在做梦，放行", None, None
        
        if not message or not message.message_info:
            return True, True, "无消息信息，放行", None, None
        
        group_id = message.chat_stream.stream_id
        dream_groups = get_dream_groups()
        
        if group_id in dream_groups:
            logger.info(f"[梦境拦截] 群 {group_id} 正在做梦，拦截消息")
            return True, False, "做梦中，消息已拦截", None, None
        
        return True, True, "非做梦群，放行", None, None


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

        valid_groups = [g for g in sync_groups if g and str(g).strip()]
        if not valid_groups:
            logger.info("[麦上号] 配置的群号均为空，跳过同步")
            return True, True, "群号配置为空", None, None
        
        if len(valid_groups) != len(sync_groups):
            logger.warning(f"[麦上号] 过滤了 {len(sync_groups) - len(valid_groups)} 个空群号")

        if not bot_qq:
            bot_qq = str(global_config.bot.qq_account)

        logger.info(f"[麦上号] 等待 {sync_delay} 秒后开始同步...")
        await asyncio.sleep(sync_delay)

        api = NapCatAPI(napcat_url, access_token)

        try:
            total_synced = 0
            total_skipped = 0
            synced_groups_info: List[Dict[str, Any]] = []

            for group_id in valid_groups:
                group_id_str = str(group_id).strip()
                logger.info(f"[麦上号] 正在同步群 {group_id_str} 的消息...")
                
                synced, skipped, latest_msg = await self._sync_group_messages(
                    api=api,
                    group_id=group_id_str,
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
        existing_message_times = await self._get_existing_message_times(stream_id)

        synced = 0
        skipped = 0
        latest_msg_info: Optional[Dict] = None
        
        processed_messages: List[Dict] = []
        
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

                is_duplicate = False
                if dedupe_mode == "message_id" and msg_id and msg_id in existing_message_ids:
                    is_duplicate = True
                elif dedupe_mode == "content_hash":
                    content_hash = self._generate_content_hash(sender_id, msg_time, content)
                    if content_hash in existing_message_hashes:
                        is_duplicate = True

                processed_messages.append({
                    "msg_id": msg_id,
                    "msg_time": msg_time,
                    "sender_id": sender_id,
                    "sender_name": sender_name,
                    "sender_card": sender_card,
                    "content": content,
                    "is_duplicate": is_duplicate,
                })
                
                if is_duplicate:
                    skipped += 1
                else:
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

        if not processed_messages:
            logger.info(f"[麦上号] 群 {group_id} 没有需要处理的消息")
            return 0, 0, None

        offline_segments = self._identify_offline_segments(
            processed_messages, existing_message_times
        )
        
        logger.info(f"[麦上号] 群 {group_id} 识别到 {len(offline_segments)} 个离线消息段落")

        for segment in offline_segments:
            segment_synced = await self._store_offline_segment(
                stream_id=stream_id,
                group_id=group_id,
                segment_messages=segment,
                add_markers=add_markers,
            )
            synced += segment_synced

        logger.info(
            f"[麦上号] 群 {group_id} 同步完成：新增 {synced} 条，跳过 {skipped} 条"
        )
        return synced, skipped, latest_msg_info

    def _identify_offline_segments(
        self, 
        processed_messages: List[Dict], 
        existing_times: Set[float]
    ) -> List[List[Dict]]:
        """识别离线消息段落
        
        离线消息段落是指：
        1. 连续的新消息（非重复）
        2. 被已知消息"夹在中间"或"在最前面"或"在最后面"
        
        Returns:
            离线消息段落列表，每个段落是一个消息列表
        """
        segments: List[List[Dict]] = []
        current_segment: List[Dict] = []
        
        sorted_messages = sorted(processed_messages, key=lambda x: x["msg_time"])
        
        for msg in sorted_messages:
            if msg["is_duplicate"]:
                if current_segment:
                    segments.append(current_segment)
                    current_segment = []
            else:
                current_segment.append(msg)
        
        if current_segment:
            segments.append(current_segment)
        
        return segments

    async def _store_offline_segment(
        self,
        stream_id: str,
        group_id: str,
        segment_messages: List[Dict],
        add_markers: bool = True,
    ) -> int:
        """存储一个离线消息段落
        
        Returns:
            成功存储的消息数（包含标记消息）
        """
        if not segment_messages:
            return 0
            
        synced = 0
        first_msg = segment_messages[0]
        last_msg = segment_messages[-1]
        
        if add_markers:
            success = await self._store_marker_message(
                stream_id=stream_id,
                group_id=group_id,
                msg_time=first_msg["msg_time"] - 0.1,
                marker_type="start",
            )
            if success:
                synced += 1
        
        for msg_data in segment_messages:
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
        
        if add_markers:
            success = await self._store_marker_message(
                stream_id=stream_id,
                group_id=group_id,
                msg_time=last_msg["msg_time"] + 0.1,
                marker_type="end",
            )
            if success:
                synced += 1
        
        return synced

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
            from src.chat.message_receive.chat_stream import get_chat_manager
            from src.chat.message_receive.message import MessageRecv
            from maim_message import UserInfo, GroupInfo, BaseMessageInfo, Seg
            
            for group_info in groups_info:
                stream_id = group_info["stream_id"]
                group_id = group_info["group_id"]
                latest_msg = group_info.get("latest_message")
                
                if not latest_msg:
                    continue
                
                logger.info(f"[麦上号] 为群 {group_id} 触发 planner...")
                
                try:
                    chat_manager = get_chat_manager()
                    chat_stream = chat_manager.get_stream(stream_id)
                    
                    if chat_stream and chat_stream.context is None:
                        sender_id = latest_msg.get("sender_id", "")
                        sender_name = latest_msg.get("sender_name", "")
                        content = latest_msg.get("content", "")
                        msg_time = latest_msg.get("time", time.time())
                        
                        user_info = UserInfo(
                            platform="qq",
                            user_id=sender_id,
                            user_nickname=sender_name,
                            user_cardname="",
                        )
                        
                        message_dict = {
                            "message_info": {
                                "platform": "qq",
                                "message_id": latest_msg.get("message_id", f"offline_{msg_time}"),
                                "time": msg_time,
                                "group_info": {
                                    "platform": "qq",
                                    "group_id": group_id,
                                    "group_name": "",
                                },
                                "user_info": user_info.to_dict(),
                            },
                            "message_segment": {
                                "type": "text",
                                "data": {"text": content},
                            },
                            "processed_plain_text": content,
                        }
                        
                        fake_message = MessageRecv(message_dict)
                        chat_stream.set_context(fake_message)
                        logger.debug(f"[麦上号] 已为群 {group_id} 设置消息上下文")
                    
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

    async def _get_existing_message_times(self, stream_id: str) -> Set[float]:
        """获取数据库中已存在的消息时间戳集合"""
        try:
            messages = await asyncio.to_thread(
                lambda: list(
                    Messages.select(Messages.time)
                    .where(Messages.chat_id == stream_id)
                    .execute()
                )
            )
            return {msg.time for msg in messages if msg.time}
        except Exception as e:
            logger.error(f"[麦上号] 获取已存在消息时间戳失败: {e}")
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
        """从消息中提取文本内容
        
        NapCat 返回的消息结构可能有：
        - message: 数组格式 [{type: "text", data: {text: "..."}}, ...]
        - content: 字符串或数组（某些版本）
        - raw_message: CQ码格式字符串
        """
        message = msg.get("message", [])
        if isinstance(message, list) and message:
            texts = []
            for seg in message:
                if isinstance(seg, dict):
                    seg_type = seg.get("type", "")
                    seg_data = seg.get("data", {})
                    if seg_type == "text":
                        texts.append(seg_data.get("text", ""))
                    elif seg_type == "at":
                        qq = seg_data.get("qq", "")
                        texts.append(f"[AT:{qq}]")
                    elif seg_type == "face":
                        texts.append("[表情]")
                    elif seg_type == "image":
                        texts.append("[图片]")
                    elif seg_type == "record":
                        texts.append("[语音]")
                    elif seg_type == "video":
                        texts.append("[视频]")
                    elif seg_type == "reply":
                        texts.append("[回复]")
                    else:
                        texts.append(f"[{seg_type}]")
            return "".join(texts)
        
        content = msg.get("content", [])
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            texts = []
            for seg in content:
                if isinstance(seg, dict) and seg.get("type") == "text":
                    texts.append(seg.get("data", {}).get("text", ""))
            result = "".join(texts)
            if result.strip():
                return result
        
        raw_message = msg.get("raw_message", "")
        if isinstance(raw_message, str) and raw_message.strip():
            return raw_message
        
        return ""


@register_plugin
class MaiShangHaoPlugin(BasePlugin):
    """麦上号 - 离线消息同步 + 做梦插件"""

    plugin_name: str = "mai_shang_hao"
    enable_plugin: bool = False
    dependencies: List[str] = []
    python_dependencies: List[str] = ["aiohttp"]
    config_file_name: str = "config.toml"

    config_section_descriptions = {
        "plugin": "插件基本信息",
        "napcat": "NapCat API 配置",
        "sync": "离线消息同步配置",
        "dream": "做梦功能配置",
    }

    config_schema: dict = {
        "plugin": {
            "config_version": ConfigField(
                type=str, default="1.3.0", description="配置文件版本"
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
        "dream": {
            "enabled": ConfigField(
                type=bool,
                default=False,
                description="是否启用做梦功能",
            ),
            "admin_users": ConfigField(
                type=list,
                default=[],
                description="梦境管理命令的管理员用户ID列表，留空则没人可用（必须配置才能使用命令）",
            ),
            "groups": ConfigField(
                type=list,
                default=[],
                description="做梦的群号列表，如 [123456789, 987654321]",
            ),
            "times": ConfigField(
                type=list,
                default=["03:00-04:00"],
                description="做梦时间段列表，支持多个时间段，如 ['03:00-04:00', '14:00-15:00']",
            ),
            "dreams_per_day": ConfigField(
                type=int,
                default=1,
                description="每个群每天做梦的次数，默认1次",
            ),
            "dream_interval_minutes": ConfigField(
                type=int,
                default=60,
                description="同一群多次做梦的最小间隔（分钟），仅当 dreams_per_day > 1 时生效",
            ),
            "check_interval": ConfigField(
                type=int,
                default=60,
                description="检查是否到做梦时间的间隔（秒）",
            ),
            "personality_traits": ConfigField(
                type=str,
                default="此处填入你的bot人格",
                description="梦境中保持的人格特质（请根据bot_config.toml中的personality填写）",
            ),
        },
    }

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        return [
            (MaiShangHaoHandler.get_handler_info(), MaiShangHaoHandler),
            (DreamHandler.get_handler_info(), DreamHandler),
            (DreamMessageInterceptor.get_handler_info(), DreamMessageInterceptor),
            (DreamCommand.get_command_info(), DreamCommand),
        ]
