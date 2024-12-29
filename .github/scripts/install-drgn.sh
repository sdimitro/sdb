#!/bin/bash -eux

#
# These are build requirements of "drgn"; if we don't install these, the
# build/install of "drgn" will fail below.
#
sudo apt update
sudo apt install autoconf automake check gcc git liblzma-dev libelf-dev libdw-dev libtool make pkgconf python3 python3-dev python3-pip python3-setuptools zlib1g-dev bison flex

git clone https://github.com/osandov/drgn.git

cd drgn
python3 setup.py install
cd -
