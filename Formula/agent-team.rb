class AgentTeam < Formula
  include Language::Python::Virtualenv

  desc "Portable native agent-team workflow generator"
  homepage "https://github.com/dearrrfish/agent-team"
  url "https://github.com/dearrrfish/agent-team/archive/refs/tags/v0.3.0.tar.gz"
  sha256 "414aaff88bdc84e4b403a6c4cb65ab2990c3ff2367d8c76711e83cdbc12dde07"
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
