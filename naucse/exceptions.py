class UntrustedRepo(Exception):
    """Raised when we'd need to execute code from an untrusted repo."""
    def __init__(self, url):
        super().__init__(url)
        self.url =url
