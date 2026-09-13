{
  description = "Portable native agent-team workflow generator";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      supportedSystems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
    in {
      packages = forAllSystems (system:
        let pkgs = import nixpkgs { inherit system; };
        in {
          default = pkgs.python3Packages.buildPythonApplication {
            pname = "agent-team";
            version = "0.1.0";
            pyproject = true;
            src = self;
            build-system = [ pkgs.python3Packages.setuptools ];
            nativeCheckInputs = [ pkgs.git ];
            checkPhase = ''
              runHook preCheck
              python -m unittest discover -s tests -v
              runHook postCheck
            '';
          };
        });

      apps = forAllSystems (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/agent-team";
          meta.description = "Portable native agent-team workflow generator";
        };
      });

      devShells = forAllSystems (system:
        let pkgs = import nixpkgs { inherit system; };
        in {
          default = pkgs.mkShell {
            packages = [ pkgs.python311 pkgs.git ];
            shellHook = ''
              export PYTHONPATH="$PWD/src''${PYTHONPATH:+:$PYTHONPATH}"
            '';
          };
        });

      checks = forAllSystems (system: {
        inherit (self.packages.${system}) default;
      });
    };
}
