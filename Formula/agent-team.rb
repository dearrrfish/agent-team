class AgentTeam < Formula
  include Language::Python::Virtualenv

  desc "Portable native agent-team workflow generator"
  homepage "https://github.com/dearrrfish/agent-team"
  url "https://github.com/dearrrfish/agent-team/archive/refs/tags/v0.5.0.tar.gz"
  sha256 "b64b2d40cd4fbe4a2cc320e35416f8980d32db966f673d6748d3fd73cdb2bd12"
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
