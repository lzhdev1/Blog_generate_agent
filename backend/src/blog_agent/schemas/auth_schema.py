"""用户认证相关请求/响应模型"""
import datetime
import re

from pydantic import BaseModel, EmailStr, Field, field_validator

# 用户名：仅数字 + 大小写字母，3-32 位
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9]{3,32}$")
# 密码：8-32 位，允许大小写字母、数字、下划线和安全符号（避开引号/括号/分号等易混淆、易注入顾虑的字符）
PASSWORD_PATTERN = re.compile(r"^[A-Za-z0-9_!@#$%^&*+\-=]{8,32}$")
# 昵称：2-32 位，允许中文、字母、数字、下划线、空格
NICKNAME_PATTERN = re.compile(r"^[\u4e00-\u9fa5A-Za-z0-9_ ]{2,32}$")


class RegisterReq(BaseModel):
    """注册请求：昵称（默认 Blog_ + 随机5位数）、邮箱+验证码、用户名、密码、确认密码"""
    nickname: str = Field(..., min_length=2, max_length=32)
    email: EmailStr
    email_code: str = Field(..., min_length=6, max_length=6, description="邮箱验证码（开发阶段固定 888888）")
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=8, max_length=32)
    confirm_password: str = Field(..., min_length=8, max_length=32)

    @field_validator("username")
    @classmethod
    def check_username(cls, v: str) -> str:
        if not USERNAME_PATTERN.match(v):
            raise ValueError("用户名只能是数字和大小写字母，长度 3-32 位")
        return v

    @field_validator("password")
    @classmethod
    def check_password(cls, v: str) -> str:
        if not PASSWORD_PATTERN.match(v):
            raise ValueError("密码 8-32 位，只能包含大小写字母、数字、下划线及 !@#$%^&*+-= 符号")
        if not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v):
            raise ValueError("密码必须同时包含字母和数字")
        return v

    @field_validator("nickname")
    @classmethod
    def check_nickname(cls, v: str) -> str:
        v = v.strip()
        if not NICKNAME_PATTERN.match(v):
            raise ValueError("昵称 2-32 位，支持中文、字母、数字、下划线")
        return v


class LoginReq(BaseModel):
    """登录请求：用户名或邮箱 + 密码"""
    account: str = Field(..., min_length=1, max_length=128, description="用户名或邮箱")
    password: str = Field(..., min_length=1, max_length=64)


class SendCodeReq(BaseModel):
    """发送邮箱验证码"""
    email: EmailStr


class RechargeReq(BaseModel):
    """模拟充值（开发期用，后续接真实支付网关）"""
    amount: float = Field(..., gt=0, le=10000, description="充值金额（元）")


class ChangePasswordReq(BaseModel):
    """修改密码"""
    old_password: str = Field(..., min_length=1, max_length=64)
    new_password: str = Field(..., min_length=8, max_length=32)
    confirm_new_password: str = Field(..., min_length=8, max_length=32)

    @field_validator("new_password")
    @classmethod
    def check_new_password(cls, v: str) -> str:
        if not PASSWORD_PATTERN.match(v):
            raise ValueError("新密码 8-32 位，只能包含大小写字母、数字、下划线及 !@#$%^&*+-= 符号")
        if not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v):
            raise ValueError("新密码必须同时包含字母和数字")
        return v


class UserResp(BaseModel):
    """用户信息响应"""
    id: int
    username: str
    email: str
    nickname: str
    email_verified: bool
    balance: float
    created_at: datetime.datetime | None = None

    model_config = {"from_attributes": True}


class TokenResp(BaseModel):
    """登录/注册成功响应"""
    access_token: str
    token_type: str = "bearer"
    user: UserResp
