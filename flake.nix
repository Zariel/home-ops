{
  description = "home-ops devShell";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    talhelper.url = "github:budimanjojo/talhelper";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
      ...
    }@inputs:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfreePredicate = pkg: builtins.elem (nixpkgs.lib.getName pkg) [
            "1password-cli"
          ];
        };
      in
      {
        devShells.default = pkgs.mkShell {
          name = "home-ops-dev";
          buildInputs = with pkgs; [
            inputs.talhelper.packages.${system}.default
            talosctl
            butane
            minijinja
            yq-go
            jq
            curl
            openssl
            python3
            rsync
            gitMinimal
            openssh
            _1password-cli
            go-task
            age
            gnupg
            kubectl
            kustomize
            fluxcd
            actionlint
          ];
        };
      }
    );
}
