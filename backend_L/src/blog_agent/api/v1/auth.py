"""用户认证 API：注册 / 登录 / 当前用户 / 改密 / 注销 / 验证码 / 模拟充值（从旧版移植）"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from config.settings import settings
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
from src.blog_agent.service.email_verification import issue_code, require_registration
from src.blog_agent.service.quota_service import limit_auth, quota_for

router = APIRouter(prefix="/api/v1/auth", tags=["用户认证"])


@router.get("/config", summary="注册方式与测试环境提示")
def public_config():
    mode = settings.effective_registration
    return {"registration_mode": mode,
            "test_code": settings.email_code_default if mode == "test" else None,
            "demo_recharge_enabled": settings.demo_recharge_enabled}


@router.get("/quota", summary="当前账户的生成额度")
def get_quota(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return quota_for(db, user.id)


@router.post("/send-code", summary="申请注册验证码")
def send_code(req: SendCodeReq, request: Request, db: Session = Depends(get_db)):
    require_registration()
    email = str(req.email).strip().lower()
    limit_auth(db, request, "send", email)
    return issue_code(db, email)


@router.post("/register", response_model=TokenResp, summary="用户注册")
def register(req: RegisterReq, request: Request, db: Session = Depends(get_db)):
    require_registration()
    limit_auth(db, request, "register", str(req.email))
    user = auth_service.register_user(
        db,
        nickname=req.nickname,
        email=req.email,
        email_code=req.email_code,
        username=req.username,
        password=req.password,
        confirm_password=req.confirm_password,
    )
    return {"access_token": auth_service.token_for_user(db, user), "user": user}


@router.post("/login", response_model=TokenResp, summary="登录（用户名或邮箱）")
def login(req: LoginReq, request: Request, db: Session = Depends(get_db)):
    limit_auth(db, request, "login", req.account)
    user = auth_service.authenticate_user(db, req.account, req.password)
    return {"access_token": auth_service.token_for_user(db, user), "user": user}


@router.get("/me", response_model=UserResp, summary="获取当前登录用户")
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/password", summary="修改密码")
def change_password(req: ChangePasswordReq, request: Request, current_user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    limit_auth(db, request, "password", str(current_user.id))
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
def recharge(req: RechargeReq, current_user: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    """模拟支付闭环：支付确认码固定为 888888（settings.email_code_default）。
    将来接真实支付网关时，此接口改为由支付回调驱动，前端逻辑不变。
    """
    if not settings.demo_recharge_enabled:
        raise HTTPException(403, detail="该环境未开放模拟充值")
    if req.verify_code != settings.email_code_default:
        raise HTTPException(status_code=400, detail="模拟充值确认码错误")
    db.refresh(current_user, with_for_update=True)
    user = auth_service.recharge_balance(db, current_user, req.amount)
    return {"message": "充值成功", "balance": float(user.balance)}
