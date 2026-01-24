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
        pkgs = import nixpkgs { inherit system; };
      in
      {
        devShells.default = pkgs.mkShell {
          name = "home-ops-dev";
          buildInputs = with pkgs; [
            inputs.talhelper.packages.${system}.default
            talosctl
            yq-go
            jq
            curl
            rsync
            gitMinimal
            openssh
            go-task
            age
            gnupg
            kubectl
            kustomize
            fluxcd
          ];
        };
      }
    );
}
