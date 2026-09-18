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
            nativeCheckInputs = [ pkgs.git pkgs.ruff ];
            checkPhase = ''
              runHook preCheck
              ruff check src tests
              python -m unittest discover -s tests -v
              runHook postCheck
            '';
            meta = {
              description = "Portable native agent-team workflow generator";
              homepage = "https://github.com/dearrrfish/agent-team";
              license = pkgs.lib.licenses.mit;
              mainProgram = "agent-team";
              platforms = supportedSystems;
            };
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

      checks = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          package = self.packages.${system}.default;
        in {
          inherit (self.packages.${system}) default;

          release-smoke = pkgs.runCommand "agent-team-release-smoke" {
            nativeBuildInputs = [ pkgs.bash pkgs.git pkgs.shellcheck ];
          } ''
            shellcheck ${self}/tests/release_smoke.sh
            bash ${self}/tests/release_smoke.sh \
              ${package}/bin/agent-team "$TMPDIR/project"
            touch $out
          '';

          documentation = pkgs.runCommand "agent-team-documentation" {
            nativeBuildInputs = [ pkgs.markdownlint-cli2 ];
          } ''
            markdownlint-cli2 --config ${self}/.markdownlint-cli2.jsonc \
              '${self}/*.md' '${self}/docs/**/*.md' '${self}/.github/**/*.md'
            touch $out
          '';
        });
    };
}
