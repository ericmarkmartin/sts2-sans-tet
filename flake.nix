{
  description = "Development shell for the STS2 RL training harness";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      supportedSystems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
    in {
      devShells = forAllSystems (system:
        let pkgs = import nixpkgs { inherit system; };
        in {
          default = pkgs.mkShell {
            packages = with pkgs; [
              dotnet-sdk_9
              ffmpeg
              python311
              uv
            ];
            DOTNET_CLI_TELEMETRY_OPTOUT = "1";
          };
        });
    };
}
