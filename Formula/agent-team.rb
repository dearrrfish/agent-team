class AgentTeam < Formula
  include Language::Python::Virtualenv

  desc "Portable native agent-team workflow generator"
  homepage "https://github.com/dearrrfish/agent-team"
  url "https://github.com/dearrrfish/agent-team/archive/refs/tags/v0.4.1.tar.gz"
  sha256 "5c39122d28ab354e8ffb653df73ae7f70b07f5365bd469fcd23de0f120463f59"
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
