{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  packages = [ pkgs.python311 pkgs.git ];
  shellHook = ''
    export PYTHONPATH="$PWD/src''${PYTHONPATH:+:$PYTHONPATH}"
  '';
}
