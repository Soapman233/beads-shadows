"""Create a new administrator from an interactive terminal."""
import argparse
import getpass
import uuid

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from .auth import User, normalized_username, password_hasher
from .db import session_factory


def main():
    parser = argparse.ArgumentParser(description="创建新的豆影管理员")
    parser.add_argument("username")
    arguments = parser.parse_args()
    try:
        username = normalized_username(arguments.username)
        factory = session_factory()
    except (HTTPException, ValueError) as error:
        parser.error(error.detail if isinstance(error, HTTPException) else str(error))
    password = getpass.getpass("管理员密码（10–128 字符）: ")
    if not 10 <= len(password) <= 128:
        parser.error("密码长度需为 10–128 字符")
    if password != getpass.getpass("确认密码: "):
        parser.error("两次输入不一致")
    with factory() as database:
        database.add(User(id=str(uuid.uuid4()), username=username, nickname=username,
                          password_digest=password_hasher.hash(password), role="admin"))
        try:
            database.commit()
        except IntegrityError:
            parser.error("账号已存在。请使用其他用户名创建管理员")
    print(f"已创建管理员 {username}")


if __name__ == "__main__":
    main()
