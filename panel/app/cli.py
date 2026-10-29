"""Small CLI for scripted setup.

  python -m app.cli add-node --name Amsterdam --flag 🇳🇱 --address 1.2.3.4 [--sni www.microsoft.com]

Prints the node token. Idempotent: if a node with this address exists, prints its token.
"""
import argparse

from sqlalchemy import select

from .db import SessionLocal, init_db
from .models import Node


def add_node(args) -> None:
    init_db()
    with SessionLocal() as db:
        node = db.scalar(select(Node).where(Node.address == args.address))
        if node is None:
            node = Node(name=args.name, flag=args.flag, address=args.address, sni=args.sni)
            db.add(node)
            db.commit()
        print(node.token)


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(required=True)
    p = sub.add_parser("add-node")
    p.add_argument("--name", required=True)
    p.add_argument("--flag", default="🌐")
    p.add_argument("--address", required=True)
    p.add_argument("--sni", default="www.microsoft.com")
    p.set_defaults(func=add_node)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
