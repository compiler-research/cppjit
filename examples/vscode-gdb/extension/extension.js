// Runs gdb's own DAP server (gdb -i dap, gdb 16 or later) with the cppjit gdb extension loaded,
// behind dap-proxy.js, which adds Python line breakpoints.
"use strict";

const vscode = require("vscode");
const childProcess = require("child_process");
const fs = require("fs");
const path = require("path");

const TYPE = "cppjit-gdb";
// find_spec does not import cppjit, so no JIT starts.
const FIND_SCRIPT =
    "import importlib.util as u, os; " +
    "print(os.path.join(u.find_spec('cppjit').submodule_search_locations[0], 'debugger', 'gdb', 'cppjit_gdb.py'))";

function onPath(program, env) {
    if (program.includes(path.sep)) {
        return program;
    }
    for (const dir of (env.PATH || "").split(path.delimiter)) {
        const candidate = path.join(dir, program);
        if (fs.existsSync(candidate)) {
            return candidate;
        }
    }
    return program;
}

function activate(context) {
    context.subscriptions.push(
        vscode.debug.registerDebugConfigurationProvider(TYPE, {
            resolveDebugConfiguration(folder, config) {
                // gdb's launch request replaces the whole environment of the process.
                config.env = { ...process.env, ...(config.env || {}) };
                config.program = onPath(config.program || "python3", config.env);
                return config;
            },
        }),
        vscode.debug.registerDebugAdapterDescriptorFactory(TYPE, {
            createDebugAdapterDescriptor(session) {
                const config = session.configuration;
                const script =
                    config.cppjitGdbScript ||
                    childProcess.execFileSync(config.program, ["-c", FIND_SCRIPT], { env: config.env, encoding: "utf8" }).trim();
                // The extension host's own Node runs the proxy; Electron needs ELECTRON_RUN_AS_NODE for that.
                return new vscode.DebugAdapterExecutable(
                    process.execPath,
                    [
                        path.join(__dirname, "dap-proxy.js"), config.gdb || "gdb", "-i", "dap", "-iex", `source ${script}`,
                        "-iex", `set cppjit internal-frames ${config.internalFrames === "show" ? "show" : "hide"}`,
                    ],
                    { env: { ELECTRON_RUN_AS_NODE: "1" } },
                );
            },
        }),
    );
}

function deactivate() {}

module.exports = { activate, deactivate };
