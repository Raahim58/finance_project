from cryptography.fernet import Fernet


def generate_encryption_key() -> str:
    return Fernet.generate_key().decode("utf-8")


if __name__ == "__main__":
    print(generate_encryption_key())
