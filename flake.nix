{
  description = "Scribe application using uv2nix";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";

    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { nixpkgs, pyproject-nix, uv2nix, pyproject-build-systems, ... }:
    let
      inherit (nixpkgs) lib;
      forAllSystems = lib.genAttrs lib.systems.flakeExposed;

      workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ./.; };

      overlay = workspace.mkPyprojectOverlay { sourcePreference = "wheel"; };

      editableOverlay =
        workspace.mkEditablePyprojectOverlay { root = "$REPO_ROOT"; };

      pythonSets = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          python = pkgs.python313;
          pyprojectOverrides = final: prev:
            let hacks = final.pkgs.callPackage pyproject-nix.build.hacks { };
            in {
              # Use nixpkgs versions to avoid building from source
              pycairo = hacks.nixpkgsPrebuilt {
                from = final.pkgs.python3Packages.pycairo;
                prev = prev.pycairo;
              };
              # pygobject in PyPI is pygobject3 in nixpkgs
              pygobject = hacks.nixpkgsPrebuilt {
                from = final.pkgs.python3Packages.pygobject3;
                prev = prev.pygobject;
              };
            };
        in (pkgs.callPackage pyproject-nix.build.packages {
          inherit python;
        }).overrideScope (lib.composeManyExtensions [
          pyproject-build-systems.overlays.wheel
          overlay
          pyprojectOverrides
        ]));

    in {
      devShells = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          pythonSet = pythonSets.${system}.overrideScope editableOverlay;
          virtualenv =
            pythonSet.mkVirtualEnv "scribe-dev-env" { scribe = [ "app" ]; };
          gtkDeps = with pkgs; [
            gcc
            pkg-config
            cairo
            glib
            gobject-introspection
            gtk3
            gdk-pixbuf
            pango
            libayatana-appindicator
          ];
        in {
          default = pkgs.mkShell {
            packages = [ virtualenv pkgs.uv ] ++ gtkDeps;
            env = {
              UV_NO_SYNC = "1";
              UV_PYTHON = pythonSet.python.interpreter;
              UV_PYTHON_DOWNLOADS = "never";
              GI_TYPELIB_PATH = lib.makeSearchPath "lib/girepository-1.0" [
                pkgs.gobject-introspection
                pkgs.gtk3
                pkgs.gdk-pixbuf
                pkgs.pango
                pkgs.libayatana-appindicator
              ];
              PKG_CONFIG_PATH =
                lib.makeSearchPath "lib/pkgconfig" [ pkgs.glib ];
              XDG_DATA_DIRS = lib.makeSearchPath "share" [
                pkgs.gtk3
                pkgs.gdk-pixbuf
                pkgs.pango
                pkgs.libayatana-appindicator
              ];
            };
            shellHook = ''
              unset PYTHONPATH
              export REPO_ROOT=$(git rev-parse --show-toplevel)
            '';
          };
        });

      packages = forAllSystems (system: {
        default = pythonSets.${system}.mkVirtualEnv "scribe-env" {
          scribe = [ "app" ];
        };
      });
    };
}
