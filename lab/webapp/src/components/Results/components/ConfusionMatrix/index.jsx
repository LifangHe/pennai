require('es6-promise').polyfill();
import fetch from 'isomorphic-fetch';
import React, { Component } from 'react';
import InvertedCard from '../../../InvertedCard';
import { Header, Image, Loader } from 'semantic-ui-react';

class ConfusionMatrix extends Component {
  constructor(props) {
    super(props);
    this.state = { image_url: null };
  }

  componentDidMount() {
    const { file } = this.props;

    if(file) {
      fetch(`/api/v1/files/${file._id}`)
        .then(response => {
          if(response.status >= 400) {
            throw new Error(`${response.status}: ${response.statusText}`);
          }  
          return response.blob();
        })
        .then(blob => {
          this.setState({ 
            image_url: URL.createObjectURL(blob) 
          });
        });
    }
  }

  render() {
    const { file } = this.props;
    const { image_url } = this.state;

    if(!file) {
      return (
        <Header inverted size="tiny" content="Confusion matrix is not available." />
      );
    }

    if(!image_url) {
      return (
        <Loader active inverted inline="centered" content="Retrieving confusion matrix..." />
      );
    }

    return (
      <InvertedCard
        header="Confusion Matrix"
        content={<Image src={image_url} />}
      />
    );
  }
}

export default ConfusionMatrix;
