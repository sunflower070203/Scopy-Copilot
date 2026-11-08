# Third-party components

The portable distribution includes a separate executable built from Analog Devices'
unmodified Scopy MCP server at the Scopy v2.2.1 tag. That server is licensed under
GPL-3.0-or-later. Its source, license, original README and download hashes are in
`third-party-source/scopy-mcp-server/` in the portable package and
`vendor/scopy-mcp-server/` in this repository.

Upstream: https://github.com/analogdevicesinc/scopy/tree/v2.2.1/tools/scopy-mcp-server

The GUI communicates with that separate process over stdio MCP. It only exposes
fixed read-only operations to the model. The upstream server's general-purpose
API is not exposed as a model tool by this application.

Python, Tcl/Tk, the MCP Python SDK, pywin32, PyInstaller and their dependencies retain
their respective licenses. The portable package includes available installed
license/notice files and a dependency inventory under `licenses/`. Exact build
versions are recorded in BUILD-INFO.json and the build dependency lock file.

No additional license for the primary application's original source is declared
in this first upload. Public source availability does not change third-party
copyrights or grant additional rights beyond the applicable licenses.
