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
              # evdev has no Linux wheels
              evdev = hacks.nixpkgsPrebuilt {
                from = final.pkgs.python3Packages.evdev;
                prev = prev.evdev;
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
          virtualenv = pythonSet.mkVirtualEnv "scribe-dev-env" {
            scribe = [ "app" "keyboard" ];
          };
        in {
          default = pkgs.mkShell {
            packages = [ virtualenv pkgs.uv ];
            env = {
              UV_NO_SYNC = "1";
              UV_PYTHON = pythonSet.python.interpreter;
              UV_PYTHON_DOWNLOADS = "never";
            };
            shellHook = ''
              unset PYTHONPATH
              export REPO_ROOT=$(git rev-parse --show-toplevel)
            '';
          };
        });

      packages = forAllSystems (system: {
        default = pythonSets.${system}.mkVirtualEnv "scribe-env" {
          scribe = [ "app" "keyboard" ];
        };
      });
    };
}
