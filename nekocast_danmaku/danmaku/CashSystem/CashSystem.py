from loguru import logger


class User:
    '''
    用户类，包含用户的基本信息和余额等属性。
    '''
    def __init__(self, user_id: str, user_name: str, yuan: int = 0, huo: int = 0):
        self.user_id = user_id
        self.user_name = user_name
        self.yuan = yuan
        self.huo = huo

    def add_yuan(self, amount: int) -> None:
        self.yuan += amount
        logger.debug(f"用户 {self.user_name} 增加了 {amount} 元，当前余额: {self.yuan} 元")
    
    def add_huo(self, amount: int) -> None:
        self.huo += amount
        logger.debug(f"用户 {self.user_name} 增加了 {amount} 火，当前余额: {self.huo} 火")
    
    def spend_yuan(self, amount: int) -> bool:
        if self.yuan >= amount:
            self.yuan -= amount
            logger.debug(f"用户 {self.user_name} 花费了 {amount} 元，当前余额: {self.yuan} 元")
            return True
        else:
            logger.warning(f"用户 {self.user_name} 余额不足，无法花费 {amount} 元，当前余额: {self.yuan} 元")
            return False
    
    def spend_huo(self, amount: int) -> bool:
        if self.huo >= amount:
            self.huo -= amount
            logger.debug(f"用户 {self.user_name} 花费了 {amount} 火，当前余额: {self.huo} 火")
            return True
        else:
            logger.warning(f"用户 {self.user_name} 余额不足，无法花费 {amount} 火，当前余额: {self.huo} 火")
            return False
    
    def __str__(self):
        return f"User(id={self.user_id}, name={self.user_name}, yuan={self.yuan}, huo={self.huo})"    

class CashSQL:
    '''
    现金系统的数据库，实际上直接采用dict来模拟，后续可以替换为真正的数据库。
    '''
    def __init__(self, users: dict[str, User] = None):
        self.users = users if users is not None else {}
    
    def get_user(self, user_id: str) -> User | None:
        return self.users.get(user_id)
    
    def add_user(self, user: User) -> None:
        if user.user_id in self.users:
            logger.warning(f"用户 ID {user.user_id} 已存在，正在覆盖原有用户数据")
        self.users[user.user_id] = user
        logger.debug(f"添加用户 {user}")
    
    def update_user(self, user: User) -> None:
        self.users[user.user_id] = user
        logger.debug(f"更新用户 {user}")
    
    def remove_user(self, user_id: str) -> None:
        if user_id in self.users:
            removed_user = self.users.pop(user_id)
            logger.debug(f"移除用户 {removed_user}")
        else:
            logger.warning(f"尝试移除不存在的用户 ID: {user_id}")
        
    def clear(self) -> None:
        self.users.clear()
        logger.debug("清空所有用户数据")


class CashSystem:
    '''
    现金系统（CashSystem）是一个独立的模块，负责处理与现金相关的逻辑。
    '''
    def __init__(self, users: list[str]):
        self.sql = CashSQL()
        self.init_users(users)
    
    def init_user_from_groups(self, users: list[str]) -> None:
        '''
        从分组列表中初始化用户数据。
        '''
        for user_id in users:
            if self.sql.get_user(user_id) is None:
                new_user = User(user_id=user_id, user_name=f"User{user_id}")
                self.sql.add_user(new_user)
                logger.debug(f"从分组初始化用户: {new_user}")
            else:
                logger.debug(f"用户 ID {user_id} 已存在，跳过初始化")




