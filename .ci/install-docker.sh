#!/bin/bash
set -o errexit
set -o nounset

apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys 36A1D7869245C8950F966E92D8576A8BA88D21E9
echo 'deb https://get.docker.com/ubuntu docker main' > /etc/apt/sources.list.d/docker.list
apt-get install -y apt-transport-https
apt-get update
apt-get install -y "lxc-docker-$DOCKER_VERSION"
docker version
