const TARGET_PORTS = new Set([5555]);

function applyConfig(message) {
    if (!message) return;
    const proxyPort = message.port;
    const proxyIp = Array.isArray(message.proxyIp) && message.proxyIp.length === 4
        ? message.proxyIp
        : [127, 0, 0, 1];
    hookConnect(proxyPort, proxyIp);

    if (message.machineGuid) {
        hookRegistry(message.machineGuid);
    }
    if (message.computerName) {
        hookComputerName(message.computerName);
    }
    if (message.userName) {
        hookUserName(message.userName);
    }
}

rpc.exports = {
    init: applyConfig
};

recv(applyConfig);

function stringToUtf16Bytes(str) {
    const bytes = [];
    for (let i = 0; i < str.length; i++) {
        const code = str.charCodeAt(i);
        bytes.push(code & 0xff);
        bytes.push((code >> 8) & 0xff);
    }
    bytes.push(0, 0);
    return bytes;
}

function hookRegistry(machineGuid) {
    if (!machineGuid) return;

    const guidBytes = stringToUtf16Bytes(machineGuid);
    const neededSize = guidBytes.length;

    const regQueryPtr = Module.findExportByName("kernelbase.dll", "RegQueryValueExW")
        || Module.findExportByName("advapi32.dll", "RegQueryValueExW");

    if (regQueryPtr) {
        Interceptor.attach(regQueryPtr, {
            onEnter(args) {
                this.isTarget = false;
                const lpValueName = args[1];
                if (lpValueName.isNull()) return;

                try {
                    const name = lpValueName.readUtf16String();
                    if (name && name.toLowerCase() === "machineguid") {
                        this.isTarget = true;
                        this.lpType = args[3];
                        this.lpData = args[4];
                        this.lpcbData = args[5];
                    }
                } catch (e) {
                }
            },
            onLeave(retval) {
                if (!this.isTarget) return;

                try {
                    if (!this.lpcbData.isNull()) {
                        const bufferSize = this.lpcbData.readU32();

                        if (!this.lpType.isNull()) {
                            this.lpType.writeU32(1); // REG_SZ
                        }

                        if (!this.lpData.isNull() && bufferSize >= neededSize) {
                            this.lpData.writeByteArray(guidBytes);
                            this.lpcbData.writeU32(neededSize);
                            retval.replace(ptr(0)); // ERROR_SUCCESS
                        } else if (this.lpData.isNull()) {
                            this.lpcbData.writeU32(neededSize);
                            retval.replace(ptr(0)); // ERROR_SUCCESS
                        } else if (bufferSize < neededSize) {
                            this.lpcbData.writeU32(neededSize);
                            retval.replace(ptr(234)); // ERROR_MORE_DATA
                        }
                    }
                } catch (e) {
                }
            }
        });
    }
}

function hookComputerName(computerName) {
    if (!computerName) return;

    const compBytes = stringToUtf16Bytes(computerName);
    const compPtr = Module.findExportByName("kernel32.dll", "GetComputerNameW")
        || Module.findExportByName("kernelbase.dll", "GetComputerNameW");

    if (compPtr) {
        Interceptor.attach(compPtr, {
            onEnter(args) {
                this.lpBuffer = args[0];
                this.nSize = args[1];
            },
            onLeave(retval) {
                try {
                    if (!this.nSize.isNull() && !this.lpBuffer.isNull()) {
                        const maxChars = this.nSize.readU32();
                        if (maxChars > computerName.length) {
                            this.lpBuffer.writeByteArray(compBytes);
                            this.nSize.writeU32(computerName.length);
                            retval.replace(ptr(1));
                        }
                    }
                } catch (e) {
                }
            }
        });
    }
}

function hookUserName(userName) {
    if (!userName) return;

    const userBytes = stringToUtf16Bytes(userName);
    const userPtr = Module.findExportByName("advapi32.dll", "GetUserNameW")
        || Module.findExportByName("kernelbase.dll", "GetUserNameW");

    if (userPtr) {
        Interceptor.attach(userPtr, {
            onEnter(args) {
                this.lpBuffer = args[0];
                this.pcbBuffer = args[1];
            },
            onLeave(retval) {
                try {
                    if (!this.pcbBuffer.isNull() && !this.lpBuffer.isNull()) {
                        const maxChars = this.pcbBuffer.readU32();
                        if (maxChars > userName.length) {
                            this.lpBuffer.writeByteArray(userBytes);
                            this.pcbBuffer.writeU32(userName.length + 1);
                            retval.replace(ptr(1));
                        }
                    }
                } catch (e) {
                }
            }
        });
    }
}


function hookConnect(proxyPort, proxyIp) {
    const connectPtr = Process.getModuleByName("ws2_32.dll").getExportByName("connect");

    Interceptor.attach(connectPtr, {
        onEnter(args) {
            try {
                const sockaddr = args[1];
                const family = sockaddr.readU16();

                // add(byte count) moves the pointer by the requested number of bytes after sockaddr
                if (family === 2) { // IPV4
                    const port = (sockaddr.add(2).readU8() << 8) | sockaddr.add(3).readU8();

                    if (!TARGET_PORTS.has(port)) return

                    sockaddr.add(4).writeByteArray(proxyIp);
                    sockaddr.add(2).writeU8((proxyPort >> 8) & 0xFF);
                    sockaddr.add(3).writeU8(proxyPort & 0xFF);

                } else if (family === 23) { // IPV6
                    const port =
                        (sockaddr.add(2).readU8() << 8) |
                        sockaddr.add(3).readU8();

                    if (!TARGET_PORTS.has(port)) return;

                    const ipv6 = sockaddr.add(8);

                    ipv6.writeByteArray([
                        0x00, 0x00, 0x00, 0x00, // 0-3
                        0x00, 0x00, 0x00, 0x00, // 4-7
                        0x00, 0x00, 0xFF, 0xFF, // 8-11
                        proxyIp[0], proxyIp[1], proxyIp[2], proxyIp[3]
                    ]);

                    sockaddr.add(2).writeU8((proxyPort >> 8) & 0xFF);
                    sockaddr.add(3).writeU8(proxyPort & 0xFF);
                }
            }
            catch (err) {
                console.info(err.message)
            }
        }
    });
}
