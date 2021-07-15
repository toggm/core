## How to build your own Dockerimage

### Setup docker multi-arch building
https://www.docker.com/blog/multi-arch-images/

```
docker buildx create --name mybuilder
docker buildx use mybuilder
docker buildx inspect --bootstrap
```

### Build arm64 Image
```
 docker buildx build --platform linux/arm64 -t YOUR_REPO/homeassistant:YOUR_TAG --build-arg BUILD_FROM=homeassistant/aarch64-homeassistant-base:latest --build-arg BUILD_ARCH=aarch64 --build-arg=SSOCR_VERSION=2.22.1 .
 ```