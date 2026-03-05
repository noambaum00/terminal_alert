class TerminalAlert < Formula
  desc "Full-screen live terminal monitor for Israel Home Front Command (OREF) alerts"
  homepage "https://github.com/noambaum00/terminal_alert"
  head "https://github.com/noambaum00/terminal_alert.git", branch: "main"
  license "MIT"

  depends_on "python@3.12"

  def install
    python3 = Formula["python@3.12"].opt_bin/"python3.12"
    venv = libexec/"venv"

    # Create a dedicated virtualenv so the tool's dependencies are isolated
    system python3, "-m", "venv", venv
    system "#{venv}/bin/pip", "install", "--upgrade", "pip", "--quiet"
    system "#{venv}/bin/pip", "install",
           "rich>=13.0.0",
           "requests>=2.28.0",
           "--quiet"

    # Install the script into libexec to keep bin/ clean
    libexec.install "alert_watch.py"

    # Thin wrapper that invokes the virtualenv's Python
    (bin/"terminal-alert").write <<~EOS
      #!/bin/bash
      exec "#{libexec}/venv/bin/python3" "#{libexec}/alert_watch.py" "$@"
    EOS
  end

  test do
    # --help exits 0 and prints the interval flag
    assert_match "interval", shell_output("#{bin}/terminal-alert --help")
    # out-of-range interval exits 1 — exercises the venv wrapper end-to-end
    assert_match "Error", shell_output("#{bin}/terminal-alert --interval 0 2>&1", 1)
  end
end
