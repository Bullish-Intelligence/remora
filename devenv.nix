{ pkgs, lib, config, inputs, ... }:

{
  # https://devenv.sh/basics/
  env = {
    GREET = "devenv";
    PLAYWRIGHT_DRIVER_EXECUTABLE_PATH = "${pkgs.playwright-driver}/bin/playwright-driver";
    PLAYWRIGHT_BROWSERS_PATH = "${pkgs.playwright-driver.browsers}";
    PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS = true;
    PLAYWRIGHT_NODEJS_PATH = "${pkgs.nodejs}/bin/node";
  };

  # https://devenv.sh/packages/
  packages = [ 
    pkgs.git 
    pkgs.uv
    pkgs.nodejs
    pkgs.playwright
    pkgs.playwright-driver
    pkgs.playwright-driver.browsers
    pkgs.python313Packages.playwright
  ];

  # https://devenv.sh/languages/
  languages = {
    rust = {
      enable = true;
    };
    python = {
      enable = true;
      version = "3.13";
      venv.enable = true;
      uv.enable = true;
    };
  };

  # https://devenv.sh/processes/
  # processes.cargo-watch.exec = "cargo-watch";

  # https://devenv.sh/services/
  # services.postgres.enable = true;

  # https://devenv.sh/scripts/
  scripts.hello.exec = ''
    echo hello from $GREET
  '';

  enterShell = ''
    export CARGO_HOME="$DEVENV_STATE/cargo"
    export CARGO_INSTALL_ROOT="$DEVENV_STATE/cargo"
    export PATH="$CARGO_INSTALL_ROOT/bin:$PATH"

    hello
    git --version
    playwright --version
  '';

  # https://devenv.sh/tasks/
  tasks = {
    "install:allium-cli" = {
      # Skip install once the allium binary is already present in PATH.
      status = ''
        export CARGO_HOME="$DEVENV_STATE/cargo"
        export CARGO_INSTALL_ROOT="$DEVENV_STATE/cargo"
        export PATH="$CARGO_INSTALL_ROOT/bin:$PATH"
        command -v allium >/dev/null 2>&1
      '';
      exec = ''
        export CARGO_HOME="$DEVENV_STATE/cargo"
        export CARGO_INSTALL_ROOT="$DEVENV_STATE/cargo"
        export PATH="$CARGO_INSTALL_ROOT/bin:$PATH"
        cargo install --locked allium-cli
      '';
      before = [ "devenv:enterShell" "devenv:enterTest" ];
    };
  };

  # https://devenv.sh/tests/
  enterTest = ''
    echo "Running tests"
    git --version | grep --color=auto "${pkgs.git.version}"
  '';

  # https://devenv.sh/pre-commit-hooks/
  # pre-commit.hooks.shellcheck.enable = true;

  # See full reference at https://devenv.sh/reference/options/
}
