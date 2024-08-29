FIND_MULTIPLE_BROKERS_FOR_USER = (
    """SELECT credentials FROM rsa_credentials WHERE user_id = ? AND broker IN (?)"""
)
FIND_ONE_BROKER_CREDENTIALS_FOR_USER = """
                    SELECT credentials FROM rsa_credentials WHERE user_id = ? AND broker = ?
                """
