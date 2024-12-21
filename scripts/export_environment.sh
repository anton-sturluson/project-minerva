#/bin/bash
conda env export --no-builds --ignore-channels | sed '/prefix:/d' > environment.yml
