#!/bin/bash
set -o errexit
set -o nounset

apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys 36A1D7869245C8950F966E92D8576A8BA88D21E9
apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys 58118E89F3A912897C070ADBF76221572C52609D

echo 'deb https://get.docker.com/ubuntu docker main' > /etc/apt/sources.list.d/docker.list
echo 'deb https://apt.dockerproject.org/repo ubuntu-trusty main' >> /etc/apt/sources.list.d/docker.list

apt-get update
apt-get install -y apt-transport-https

if dpkg --compare-versions "$DOCKER_VERSION" ge 1.8; then
  apt-get install -y --force-yes -o 'Dpkg::Options::=--force-confnew' "docker-engine=$DOCKER_VERSION*"
else
  apt-get install -y --force-yes -o 'Dpkg::Options::=--force-confnew' "lxc-docker-$DOCKER_VERSION"
fi

docker version
