subversion=$1
version=3.$subversion
name=py3$subversion

MAMBAENV=~/.local/share/mamba/envs/$name
VENVDIR=~/.virtualenvs/$name

if [ ! -d $MAMBAENV ] ; then
	micromamba create -n $name python=$version --prefix $MAMBAENV -y
else
	echo "Environment $name already exists at $MAMBAENV"
fi
if [ ! -d $VENVDIR ] ; then
	$MAMBAENV/bin/python3 -m venv $VENVDIR
else
	echo "Virtualenv $name already exists at $VENVDIR"
fi
source ~/.virtualenvs/$name/bin/activate
pip install -U pip
pip install scribe-cli[all]