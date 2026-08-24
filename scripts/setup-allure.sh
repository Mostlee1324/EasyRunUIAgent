#!/bin/sh
# 按当前平台下载自包含的 Allure CLI + JRE 到 tools/（不依赖系统 Java / brew）。
# 幂等：已存在则跳过下载，仅重建启动器。tools/allure 与 tools/jre 为机器专属二进制，勿入版本库。
# Docker 镜像构建同样复用本脚本（容器内 uname 为 Linux，自动下载 Linux x64/aarch64 JRE）。
set -e

DIR="$(cd "$(dirname "$0")/.." && pwd)"
TOOLS="$DIR/tools"
mkdir -p "$TOOLS"

# 启动器生成（幂等）：JRE 布局随平台不同——macOS 为 jre/Contents/Home，Linux 为顶层 jre/bin/java
write_launcher() {
  mkdir -p "$TOOLS/bin"
  cat > "$TOOLS/bin/allure" <<'EOF'
#!/bin/sh
# Allure CLI 启动器：使用项目内自带的 JRE（tools/jre），不依赖系统 Java。
# JRE 布局随平台不同：macOS 为 jre/Contents/Home，Linux 为顶层 jre/bin/java。
DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [ -d "$DIR/jre/Contents/Home" ]; then
  export JAVA_HOME="$DIR/jre/Contents/Home"
else
  export JAVA_HOME="$DIR/jre"
fi
exec "$DIR/allure/bin/allure" "$@"
EOF
  chmod +x "$TOOLS/bin/allure"
}

write_launcher

if [ -x "$TOOLS/allure/bin/allure" ] \
  && { [ -x "$TOOLS/jre/Contents/Home/bin/java" ] || [ -x "$TOOLS/jre/bin/java" ]; }; then
  echo "Allure 已就绪：$TOOLS/bin/allure"
  exit 0
fi

OS="$(uname -s)"
ARCH="$(uname -m)"

# ---- Allure CLI（跨平台单一发行包，内含全部平台的 Java 启动脚本）----
if [ ! -d "$TOOLS/allure" ]; then
  echo "下载 Allure CLI…"
  curl -sL -o "$TOOLS/allure.tgz" \
    https://github.com/allure-framework/allure2/releases/download/2.32.2/allure-2.32.2.tgz
  tar xzf "$TOOLS/allure.tgz" -C "$TOOLS"
  mv "$TOOLS"/allure-2.32.2 "$TOOLS/allure"
  rm "$TOOLS/allure.tgz"
fi

# ---- JRE（按平台选择）----
if [ ! -d "$TOOLS/jre" ]; then
  case "$OS-$ARCH" in
    Darwin-x86_64) JRE_URL="https://api.adoptium.net/v3/binary/latest/11/ga/mac/x64/jre/hotspot/normal/eclipse" ;;
    Darwin-arm64)  JRE_URL="https://api.adoptium.net/v3/binary/latest/11/ga/mac/aarch64/jre/hotspot/normal/eclipse" ;;
    Linux-x86_64)  JRE_URL="https://api.adoptium.net/v3/binary/latest/11/ga/linux/x64/jre/hotspot/normal/eclipse" ;;
    Linux-aarch64) JRE_URL="https://api.adoptium.net/v3/binary/latest/11/ga/linux/aarch64/jre/hotspot/normal/eclipse" ;;
    *)
      echo "暂不支持的平台: $OS-$ARCH（请手动准备 JRE 并放到 $TOOLS/jre/Contents/Home）"
      exit 1 ;;
  esac
  echo "下载 JRE（$OS-$ARCH）…"
  curl -sL -o "$TOOLS/jre.tar.gz" "$JRE_URL"
  tar xzf "$TOOLS/jre.tar.gz" -C "$TOOLS"
  mv "$TOOLS"/jdk-11*-jre "$TOOLS/jre" 2>/dev/null || mv "$TOOLS"/jdk-11* "$TOOLS/jre"
  rm "$TOOLS/jre.tar.gz"
fi

write_launcher

"$TOOLS/bin/allure" --version && echo "Allure 就绪：$TOOLS/bin/allure"
