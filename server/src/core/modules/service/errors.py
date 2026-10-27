class UserNotFoundError(Exception):
    pass


class UserAlreadyExistsError(Exception):
    pass


class UserEmptyDataError(Exception):
    pass


class SessionNotFoundError(Exception):
    pass


class ProtectedAdminError(Exception):
    pass


class UserManagementUnavailableError(Exception):
    pass
