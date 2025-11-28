{
  description = "holywoo devShell with Talos/Matchbox tooling";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs { inherit system; };
      in
      {
        devShells.default = pkgs.mkShell {
          name = "holywoo-dev";
          buildInputs = with pkgs; [
            talhelper
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
          ];
          shellHook = ''
            if [ -f "$PWD/kubeconfig.yaml" ]; then
              export KUBECONFIG="$PWD/kubeconfig.yaml"
            fi
            if [ -f "$PWD/age.key" ]; then
              export SOPS_AGE_KEY_FILE="$PWD/age.key"
            fi
            echo "Dev shell ready (talhelper/matchbox tooling)."
          '';
        };
      }
    );
}
