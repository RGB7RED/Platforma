import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Greet a user.")
    parser.add_argument("--name", default="World", help="Name to greet")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    print(f"Hello, {args.name}!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
