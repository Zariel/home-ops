{
  description = "home-ops devShell";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      nixpkgs,
      flake-utils,
      ...
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs { inherit system; };
        topfPlatform =
          {
            x86_64-linux = {
              name = "linux_amd64";
              hash = "sha256-RY30sl9BgaMe02HAWSGU9+uebnsT5wlvh0VFOv3qrfs=";
            };
            aarch64-linux = {
              name = "linux_arm64";
              hash = "sha256-fl1L8h8HupG4PEZT62XdPPXuZ6qPpBMcpAOzh5FHY2c=";
            };
            x86_64-darwin = {
              name = "darwin_amd64";
              hash = "sha256-tMdvtZhcLgxz1qNlpa56Rfl/nWHLUCoBse6C5j2gsc0=";
            };
            aarch64-darwin = {
              name = "darwin_arm64";
              hash = "sha256-SLIhddYerboMKHQRw0qQ9z26pxb9eSt7KGJdPtv4cOI=";
            };
          }
          .${system};
        # renovate: datasource=github-releases depName=postfinance/topf
        topfVersion = "0.6.0";
        topf = pkgs.stdenvNoCC.mkDerivation {
          pname = "topf";
          version = topfVersion;
          src = pkgs.fetchurl {
            url = "https://github.com/postfinance/topf/releases/download/v${topfVersion}/topf_${topfPlatform.name}.tar.gz";
            inherit (topfPlatform) hash;
          };
          dontUnpack = true;
          nativeBuildInputs = [
            pkgs.gnutar
            pkgs.gzip
          ];
          installPhase = ''
            runHook preInstall
            mkdir -p "$out/bin"
            tar -xzf "$src" topf
            install -m755 topf "$out/bin/topf"
            runHook postInstall
          '';
        };
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
            topf
            talosctl
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
            kubectl-node-shell
            kubectl-rook-ceph
            stern
            kustomize
            fluxcd
            actionlint
          ];
          shellHook = ''
            export PATH="$PATH:''${KREW_ROOT:-$HOME/.krew}/bin"
          '';
        };
      }
    );
}
