-- Remora LSP integration for Neovim
-- Copy to ~/.config/nvim/lua/remora.lua and require("remora") in init.lua

local M = {}
local _cursor_timer = nil

M.config = {
  filetypes = { "python", "markdown", "toml" },
  cmd = { "remora", "lsp" },
  root_marker = "remora.yaml",
  web_url = "http://localhost:8080",
  cursor_tracking = true,
  cursor_debounce_ms = 300,
}

function M.setup(opts)
  opts = vim.tbl_deep_extend("force", M.config, opts or {})

  vim.api.nvim_create_autocmd("FileType", {
    pattern = opts.filetypes,
    group = vim.api.nvim_create_augroup("RemoraLSP", { clear = true }),
    callback = function()
      local root = vim.fs.root(0, { opts.root_marker })
      if not root then return end
      vim.lsp.start({
        name = "remora",
        cmd = vim.list_extend(vim.deepcopy(opts.cmd), { "--project-root", root }),
        root_dir = root,
        capabilities = vim.lsp.protocol.make_client_capabilities(),
      })
    end,
  })

  vim.api.nvim_create_autocmd({ "BufWritePost", "BufEnter", "InsertLeave" }, {
    group = vim.api.nvim_create_augroup("RemoraCodeLens", { clear = true }),
    callback = function()
      local clients = vim.lsp.get_clients({ name = "remora" })
      if #clients > 0 then
        vim.lsp.codelens.refresh()
      end
    end,
  })

  if opts.cursor_tracking then
    M._setup_cursor_tracking(opts)
  end
end

function M._setup_cursor_tracking(opts)
  if vim.o.updatetime > 500 then
    vim.o.updatetime = 300
  end

  vim.api.nvim_create_autocmd({ "CursorHold", "CursorHoldI" }, {
    group = vim.api.nvim_create_augroup("RemoraCursor", { clear = true }),
    callback = function()
      if _cursor_timer then
        _cursor_timer:stop()
        _cursor_timer = nil
      end

      _cursor_timer = vim.defer_fn(function()
        _cursor_timer = nil
        local file = vim.api.nvim_buf_get_name(0)
        if file == "" then return end
        local cursor = vim.api.nvim_win_get_cursor(0)
        local url = opts.web_url .. "/api/cursor"
        local payload = vim.fn.json_encode({
          file_path = file,
          line = cursor[1],
          character = cursor[2],
        })
        vim.fn.jobstart({
          "curl", "-s", "-X", "POST", url,
          "-H", "Content-Type: application/json",
          "-d", payload,
        }, { detach = true })
      end, opts.cursor_debounce_ms or 300)
    end,
  })
end

return M
