class AgentTeam < Formula
  include Language::Python::Virtualenv

  desc "Portable native agent-team workflow generator"
  homepage "https://github.com/dearrrfish/agent-team"
  url "https://github.com/dearrrfish/agent-team/archive/refs/tags/v0.5.1.tar.gz"
  sha256 "99acc4a223e1f4076c370434ecce535561f9430df191aeedc3a7faba48dad18f"
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
