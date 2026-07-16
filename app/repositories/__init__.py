"""数据访问层命名空间。

具体 Repository 从各自领域模块导入，避免包初始化期间产生循环依赖。
"""

__all__ = [
    "feature_repository",
    "menu_repository",
    "role_repository",
    "source_repository",
    "user_repository",
]
