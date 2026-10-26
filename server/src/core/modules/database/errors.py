class RepoNotFoundError(Exception):
    pass


class RepoAlreadyExistsError(Exception):
    pass


class RepoEmptyDataError(Exception):
    pass


class RepoProtectedAdminError(Exception):
    pass


class RepoUserManagementUnavailableError(Exception):
    pass
