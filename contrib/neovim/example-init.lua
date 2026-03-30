-- Minimal Remora configuration for neovim
-- Add to your init.lua:

-- Option 1: Default settings (assumes remora is on PATH)
require("remora").setup()

-- Option 2: Custom settings
require("remora").setup({
  web_url = "http://localhost:8080",
  cursor_tracking = true,
  filetypes = { "python" },
})
