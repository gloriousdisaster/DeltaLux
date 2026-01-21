{ pkgs, lib, config, inputs, ... }:

{
  # https://devenv.sh/basics/
  env.GREET = "DeltaLux Home Assistant Integration Development";

  # https://devenv.sh/packages/
  packages = with pkgs; [
    git
    ruff
    nodePackages.pyright
  ];

  # https://devenv.sh/languages/
  languages.python = {
    enable = true;
    version = "3.12";
    venv.enable = true;
    venv.requirements = ''
      homeassistant>=2024.1.0
      pytest
      pytest-homeassistant-custom-component
      pytest-cov
      ruff
      mypy
    '';
  };

  # https://devenv.sh/scripts/
  scripts.test.exec = ''
    pytest tests/
  '';

  scripts.lint.exec = ''
    ruff check .
  '';

  scripts.format.exec = ''
    ruff format .
  '';

  scripts.typecheck.exec = ''
    mypy --install-types --non-interactive .
  '';

  enterShell = ''
    echo "🏠 $GREET"
    echo "Python: $(python --version)"
    echo ""
    echo "Available commands:"
    echo "  test      - Run tests"
    echo "  lint      - Run ruff linter"
    echo "  format    - Format code with ruff"
    echo "  typecheck - Run mypy type checker"
  '';

  # https://devenv.sh/pre-commit-hooks/
  pre-commit.hooks = {
    ruff.enable = true;
    ruff-format.enable = true;
  };
}
