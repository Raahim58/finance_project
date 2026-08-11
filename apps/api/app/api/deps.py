# from fastapi import Depends, HTTPException, status
# from fastapi.security import OAuth2PasswordBearer
# from sqlalchemy.orm import Session

# from app.core.security import decode_access_token
# from app.db.session import get_db
# from app.models.user import User
# from app.services.auth_service import get_user_by_id

# oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# def get_current_user(
#     token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
# ) -> User:
#     user_id = decode_access_token(token)
#     if not user_id:
#         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
#     user = get_user_by_id(db, user_id)
#     if not user or not user.is_active:
#         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive or missing user")
#     return user

from secrets import compare_digest

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User
from app.services.auth_service import get_user_by_id


oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/auth/login",
    auto_error=False,
)


def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:

    # Temporary read-only demo access for external inspection
    demo_token = request.query_params.get("demo_token")

    if (
        request.method == "GET"
        and settings.enable_demo_access
        and demo_token
        and settings.demo_access_token
        and compare_digest(demo_token, settings.demo_access_token)
    ):
        user = db.scalar(
            select(User).where(
                User.email == settings.demo_access_email.lower()
            )
        )

        if user and user.is_active:
            return user

    # Normal authentication
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    user_id = decode_access_token(token)

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    user = get_user_by_id(db, user_id)

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive or missing user",
        )

    return user