"""用户认证 API：注册 / 登录 / 当前用户 / 改密 / 注销 / 验证码 / 模拟充值"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.blog_agent.api.deps import get_current_user, get_db
from src.blog_agent.db.models import User
from src.blog_agent.schemas.auth_schema import (
    ChangePasswordReq,
    LoginReq,
    RechargeReq,
    RegisterReq,
    SendCodeReq,
    TokenResp,
    UserResp,
)
from src.blog_agent.service import auth_service

router = APIRouter(prefix="/api/v1/auth", tags=["用户认证"])


@router.post("/send-code", summary="发送邮箱验证码（开发阶段返回固定 888888）")
def send_code(req: SendCodeReq):
    """开发阶段模拟发送：固定验证码 888888。
    接入真实 SMTP 后在此处生成随机码并发送邮件，前端无需改动。
    """
    from config.settings import settings
    return {"message": "验证码已发送", "email": req.email, "code": settings.email_code_default}


@router.post("/register", response_model=TokenResp, summary="用户注册")
def register(req: RegisterReq, db: Session = Depends(get_db)):
    user = auth_service.register_user(
        db,
        nickname=req.nickname,
        email=req.email,
        email_code=req.email_code,
        username=req.username,
        password=req.password,
        confirm_password=req.confirm_password,
    )
    return {"access_token": auth_service.create_access_token(user.id), "user": user}


@router.post("/login", response_model=TokenResp, summary="登录（用户名或邮箱）")
def login(req: LoginReq, db: Session = Depends(get_db)):
    user = auth_service.authenticate_user(db, req.account, req.password)
    return {"access_token": auth_service.create_access_token(user.id), "user": user}


@router.get("/me", response_model=UserResp, summary="获取当前登录用户")
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/password", summary="修改密码")
def change_password(req: ChangePasswordReq, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    auth_service.change_password(
        db, current_user,
        old_password=req.old_password,
        new_password=req.new_password,
        confirm_new_password=req.confirm_new_password,
    )
    return {"message": "密码修改成功"}


@router.delete("/account", summary="注销账号（删除用户及其全部文章）")
def delete_account(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    auth_service.deactivate_account(db, current_user)
    return {"message": "账号已注销"}


@router.post("/recharge", summary="模拟充值（开发期：模拟支付确认码 888888）")
def recharge(req: RechargeReq, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """模拟支付闭环：支付确认码固定为 888888（settings.email_code_default）。
    将来接真实支付网关时，此接口改为由支付回调驱动，前端逻辑不变。
    """
    from config.settings import settings
    if req.verify_code != settings.email_code_default:
        raise HTTPException(status_code=400, detail="支付确认码错误（开发阶段固定 888888）")
    user = auth_service.recharge_balance(db, current_user, req.amount)
    return {"message": "充值成功", "balance": float(user.balance)}
