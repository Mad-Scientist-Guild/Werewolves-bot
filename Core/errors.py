class GameError(Exception):
    """User-facing game-flow error. The global error handler replies with
    the message ephemerally instead of treating it as a crash."""


class NoActiveGame(GameError):
    pass


class GameAlreadyActive(GameError):
    pass


class NotAPlayer(GameError):
    pass
