{
  description = "home-ops devShell";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    katl.url = "github:katl-dev/katl/v2026.9.0-beta.18";
    katl.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
      katl,
      ...
    }@inputs:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs { inherit system; };
        kubectl-krew = pkgs.symlinkJoin {
          name = "kubectl-krew";
          paths = [ pkgs.krew ];
          postBuild = ''
            ln -s "$out/bin/krew" "$out/bin/kubectl-krew"
          '';
        };
      in
      {
        devShells.default = pkgs.mkShell {
          name = "home-ops-dev";
          buildInputs = with pkgs; [
            katl.packages.${system}.katlctl
            gh
            kubernetes-helm
            sops
            yq-go
            jq
            curl
            rsync
            gitMinimal
            openssh
            go-task
            age
            sops
            gnupg
            kubectl-krew
            kubectl
            kubectl-cnpg
            kubectl-node-shell
            kubectl-rook-ceph
            kubernetes-helm
            stern
            kustomize
            fluxcd
            actionlint
            prometheus.cli
          ];
          shellHook = ''
            export PATH="$PATH:''${KREW_ROOT:-$HOME/.krew}/bin"
          '';
        };
      }
    );
}
