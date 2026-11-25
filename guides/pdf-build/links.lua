-- Relative links (../README.md, SETUP_GUIDE.md) don't work inside a PDF: point them at GitHub.
local base = "https://github.com/jpat-12/TAK-PluginSuite-CrowdCAD/blob/main/"
function Link(el)
  local t = el.target
  if t:match("^%a+:") or t:match("^#") then return el end
  if t:sub(1, 3) == "../" then t = t:sub(4) else t = "guides/" .. t end
  el.target = base .. t
  return el
end
