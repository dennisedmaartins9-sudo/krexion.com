// craco.config.js
const fs = require("fs");
const path = require("path");
require("dotenv").config();

function pkgAlias(relativePath) {
  const resolved = path.resolve(__dirname, relativePath);
  return fs.existsSync(resolved) ? resolved : null;
}

// CJS entrypoints — CRA's ESM resolver chokes on lucide/framer-motion barrels.
const cjsAliases = {};
const lucideCjs = pkgAlias("node_modules/lucide-react/dist/cjs/lucide-react.js");
const motionUtilsCjs = pkgAlias("node_modules/motion-utils/dist/cjs/index.js");
const motionDomCjs = pkgAlias("node_modules/motion-dom/dist/cjs/index.js");
if (lucideCjs) cjsAliases["lucide-react"] = lucideCjs;
if (motionUtilsCjs) cjsAliases["motion-utils"] = motionUtilsCjs;
if (motionDomCjs) cjsAliases["motion-dom"] = motionDomCjs;

const ModuleScopePlugin = require("react-dev-utils/ModuleScopePlugin");

// Check if we're in development/preview mode (not production build)
// Craco sets NODE_ENV=development for start, NODE_ENV=production for build
const isDevServer = process.env.NODE_ENV !== "production";

// Environment variable overrides
const config = {
  enableHealthCheck: process.env.ENABLE_HEALTH_CHECK === "true",
  enableVisualEdits: false, // Disabled - causes babel traverse errors in this environment
};

// Conditionally load visual edits modules only in dev mode
let setupDevServer;
let babelMetadataPlugin;

if (config.enableVisualEdits) {
  setupDevServer = require("./plugins/visual-edits/dev-server-setup");
  babelMetadataPlugin = require("./plugins/visual-edits/babel-metadata-plugin");
}

// Conditionally load health check modules only if enabled
let WebpackHealthPlugin;
let setupHealthEndpoints;
let healthPluginInstance;

if (config.enableHealthCheck) {
  WebpackHealthPlugin = require("./plugins/health-check/webpack-health-plugin");
  setupHealthEndpoints = require("./plugins/health-check/health-endpoints");
  healthPluginInstance = new WebpackHealthPlugin();
}

const webpackConfig = {
  eslint: {
    configure: {
      extends: ["plugin:react-hooks/recommended"],
      rules: {
        "react-hooks/rules-of-hooks": "error",
        "react-hooks/exhaustive-deps": "warn",
      },
    },
  },
  webpack: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
      ...cjsAliases,
    },
    configure: (webpackConfig) => {
      // Absolute node_modules aliases are blocked by CRA's ModuleScopePlugin
      // on Linux CI/Docker (ubuntu + alpine). Allow CJS shims when present.
      if (Object.keys(cjsAliases).length > 0) {
        webpackConfig.resolve.plugins = (webpackConfig.resolve.plugins || []).filter(
          (plugin) => !(plugin instanceof ModuleScopePlugin),
        );
      }

      // Add ignored patterns to reduce watched directories
        webpackConfig.watchOptions = {
          ...webpackConfig.watchOptions,
          ignored: [
            '**/node_modules/**',
            '**/.git/**',
            '**/build/**',
            '**/dist/**',
            '**/coverage/**',
            '**/public/**',
        ],
      };

      // Add health check plugin to webpack if enabled
      if (config.enableHealthCheck && healthPluginInstance) {
        webpackConfig.plugins.push(healthPluginInstance);
      }
      return webpackConfig;
    },
  },
};

// Only add babel metadata plugin during dev server
if (config.enableVisualEdits && babelMetadataPlugin) {
  webpackConfig.babel = {
    plugins: [babelMetadataPlugin],
  };
}

webpackConfig.devServer = (devServerConfig) => {
  // Apply visual edits dev server setup only if enabled
  if (config.enableVisualEdits && setupDevServer) {
    devServerConfig = setupDevServer(devServerConfig);
  }

  // Add health check endpoints if enabled
  if (config.enableHealthCheck && setupHealthEndpoints && healthPluginInstance) {
    const originalSetupMiddlewares = devServerConfig.setupMiddlewares;

    devServerConfig.setupMiddlewares = (middlewares, devServer) => {
      // Call original setup if exists
      if (originalSetupMiddlewares) {
        middlewares = originalSetupMiddlewares(middlewares, devServer);
      }

      // Setup health endpoints
      setupHealthEndpoints(devServer, healthPluginInstance);

      return middlewares;
    };
  }

  return devServerConfig;
};

module.exports = webpackConfig;
