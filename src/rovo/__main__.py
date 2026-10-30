"""`python -m rovo`: the same command, under the same program name, as the console script."""

if __name__ == "__main__":
    from rovo.cli import app

    app(prog_name="rovo")
