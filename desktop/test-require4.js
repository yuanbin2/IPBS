const electron = require("electron"); console.log(JSON.stringify({type: typeof electron, keys: Object.keys(electron).slice(0, 5), app: typeof electron.app}));
