from abc import ABC, abstractmethod

class BaseAuthService(ABC):
    @abstractmethod
    def login(self, username, password): ...

    @abstractmethod
    def logout(self, token): ...