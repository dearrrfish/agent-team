class AgentTeam < Formula
  include Language::Python::Virtualenv

  desc "Portable native agent-team workflow generator"
  homepage "https://github.com/dearrrfish/agent-team"
  url "https://github.com/dearrrfish/agent-team/archive/refs/tags/v0.4.0.tar.gz"
  sha256 "b910ebb2c15595906fb46437a313a7b928a9c7ecc5b2d82fa05a9a7e031ef353"
  license "MIT"
  head "https://github.com/dearrrfish/agent-team.git", branch: "main"

  depends_on "python@3.12"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "agent-team #{version}", shell_output("#{bin}/agent-team --version")
    system bin/"agent-team", "init", "--help"
  end
end
